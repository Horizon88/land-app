"""SUUMO mountain-Japan land sweep — ski-country prefectures.

Same list-page chunk parsing as scan.py's coastal sweep, but aimed at the
mountain interior: Nagano, inland Niigata, Gunma, Yamanashi, Gifu, Tochigi,
Fukushima (Aizu), Tohoku ski country, and Hokkaido ski towns.

City slugs are discovered from each prefecture's /tochi/<pref>/ index page,
then filtered against a curated keep-list of mountain municipalities (the
prefecture pages also list flatland commuter cities we don't want).

Geocoding: one Nominatim lookup per city slug (cached in
/tmp/suumo_city_geo.json), fallback to prefecture centroid.

Emits /tmp/suumo_mountain.json for suumo_mountain_merge.py.
"""
import json, os, re, subprocess, sys, time, urllib.parse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# pref slug → (display, centroid lat/lng, keep-list of city-slug substrings;
# empty list = keep every city on the index page)
PREFS = {
    "nagano":   ("Nagano",   36.65, 138.18, []),   # whole pref is mountain
    "niigata":  ("Niigata",  37.0,  138.6,  ["myoko","yuzawa","minamiuonuma","uonuma","tokamachi","itoigawa","tsunan","joetsu"]),
    "gumma":    ("Gunma",    36.5,  138.9,  ["agatsumagun","tonegun","numata","annaka","shibukawa","midori","kiryu","tomioka"]),
    "yamanashi":("Yamanashi",35.6,  138.6,  []),   # Fuji five lakes, Yatsugatake, Kofu basin edges
    "gifu":     ("Gifu",     36.0,  137.2,  ["takayama","hida","gero","gujo","ono_gun","shirakawa","nakatsugawa","ena"]),
    "tochigi":  ("Tochigi",  36.7,  139.7,  ["nikko","nasushiobara","nasugun","shioya","kanuma"]),
    "fukushima":("Fukushima",37.5,  139.9,  ["aizu","yama_gun","minamiaizu","kitakata","inawashiro","bandai"]),
    "hokkaido_":("Hokkaido", 43.0,  142.5,  ["abutagun","kutchan","niseko","furano","kamikawagun","yoichigun","otaru","chitose","eniwa","date","biei","sorachigun","yubari"]),
    "yamagata": ("Yamagata", 38.4,  140.2,  ["yamagata","yonezawa","tendo","kaminoyama","nanyo","higashiokitamagun"]),
    "akita":    ("Akita",    39.8,  140.4,  ["senboku","kazuno","daisen","yokote","yuzawa"]),
    "iwate":    ("Iwate",    39.6,  141.1,  ["shizukuishi","hachimantai","takizawa","morioka","hanamaki","kitakami","waga_gun"]),
    "aomori":   ("Aomori",   40.6,  140.6,  ["hirosaki","kuroishi","aomori","towada","hirakawa"]),
    # ── scenic / resort expansion (Fuji-Izu, hot-spring, coastal, islands) ──
    "shizuoka": ("Shizuoka", 35.00, 138.50, ["izu","atami","ito","fuji","gotemba","susono","kannami","kawazu","numazu","mishima","shimoda","matsuzaki","higashiizu","minamiizu"]),
    "kanagawa": ("Kanagawa", 35.25, 139.10, ["hakone","yugawara","odawara","ashigarashimo","ashigarakami"]),  # restrict to Hakone side
    "shiga":    ("Shiga",    35.20, 136.00, ["takashima","otsu","nagahama","maibara","kohoku","hikone","yasu"]),
    "wakayama": ("Wakayama", 33.90, 135.40, []),   # whole pref scenic (Koya, Nachi, Shirahama)
    "mie":      ("Mie",      34.30, 136.50, ["ise","shima","toba","kumano","owase","nabari","iga","minamiise"]),
    "nara":     ("Nara",     34.20, 135.90, ["yoshino","gojo","uda","tenkawa","totsukawa","kurotaki","shimokitayama","kamikitayama"]),
    "okinawa":  ("Okinawa",  26.50, 127.90, []),   # all islands scenic
    "kumamoto": ("Kumamoto", 32.90, 131.00, ["aso","minamiaso","takamori","ubuyama","oguni","kikuchi","yamaga","amakusa"]),
    "oita":     ("Oita",     33.20, 131.40, ["yufu","beppu","kokonoe","kuju","hita","taketa","kunisaki","bungo"]),
    "kagoshima":("Kagoshima",31.60, 130.60, ["kirishima","yakushima","ibusuki","minamikyushu","amami","tarumizu","kanoya","makurazaki"]),
    "ehime":    ("Ehime",    33.80, 132.80, ["matsuyama","uchiko","ozu","seiyo","kamijima","imabari","saijo","kumakogen"]),
    "kochi":    ("Kochi",    33.50, 133.50, []),   # rural / coastal Shikoku
    "ishikawa": ("Ishikawa", 37.00, 136.80, ["wajima","suzu","noto","nanao","hakui","shika","anamizu","hodatsushimizu"]),  # Noto peninsula
    "toyama":   ("Toyama",   36.70, 137.20, ["tateyama","kurobe","nyuzen","kamiichi","uozu","himi","nanto"]),
    "fukui":    ("Fukui",    35.90, 136.20, ["ono","katsuyama","echizen","obama","wakasa","tsuruga","mihama"]),
}

URL_RE = re.compile(r"/tochi/([a-z_]+)/sc_([a-z_0-9]+)/nc_(\d+)/")
SC_RE = re.compile(r"sc_([a-z_0-9]+)")
JPYUSD = 0.0064
GEO_CACHE = "/tmp/suumo_city_geo.json"


def curl(url, timeout=30):
    cmd = ["curl", "-sL", "-m", str(timeout), "-A", UA,
           "-H", "Accept-Language: ja,en;q=0.8",
           "-H", "Referer: https://suumo.jp/", url]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5).stdout
    except Exception:
        return ""


def parse_price(t):
    m = re.search(r"販売価格[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)\s*億\s*([0-9]{1,5})?\s*万円", t)
    if m:
        return int(float(m.group(1)) * 1e8 + (int(m.group(2)) if m.group(2) else 0) * 1e4)
    m = re.search(r"販売価格[^0-9]{0,8}([0-9]{1,5}(?:,[0-9]{3})*)\s*万円", t)
    if m:
        return int(m.group(1).replace(",", "")) * 10000
    return None


def parse_area(t):
    for pat in (r"土地面積\s*([0-9,]+(?:\.[0-9]+)?)\s*m\s*2",
                r"土地面積\s*([0-9,]+(?:\.[0-9]+)?)\s*㎡",
                r"土地面積\s*([0-9,]+(?:\.[0-9]+)?)\s*平米"):
        m = re.search(pat, t)
        if m:
            return float(m.group(1).replace(",", ""))
    return None


def geo_cache():
    try:
        return json.load(open(GEO_CACHE))
    except Exception:
        return {}


# Ski-country districts (gun) Nominatim can't resolve from the romaji slug —
# hand-placed at the district's main resort town.
GUN_OVERRIDES = {
    "kitaazumigun":    (36.698, 137.862),  # Hakuba / Otari
    "abutagun":        (42.75, 140.75),    # Niseko / Kutchan
    "shimotakaigun":   (36.83, 138.44),    # Nozawa Onsen / Kijimadaira
    "kitasakugun":     (36.35, 138.55),    # Karuizawa / Miyota
    "minamisakugun":   (36.03, 138.47),    # Kawakami / Nobeyama
    "chiisagatagun":   (36.35, 138.35),    # Nagawa / Aoki
    "kisogun":         (35.84, 137.69),    # Kiso valley
    "kamiminochigun":  (36.75, 138.22),    # Iizuna / Shinano
    "kamitakaigun":    (36.68, 138.36),    # Yamanouchi (Shiga Kogen)
    "tonegun":         (36.75, 139.10),    # Minakami
    "agatsumagun":     (36.58, 138.70),    # Kusatsu / Tsumagoi
    "yama_gun":        (37.60, 139.90),    # Inawashiro / Bandai
    "minamiaizugun":   (37.20, 139.60),
    "sorachigun":      (43.45, 142.47),    # Kamifurano
    "kamikawagun":     (43.55, 142.45),    # Biei / Higashikawa
    "yoichigun":       (43.20, 140.77),    # Kiroro side
    "minamitsurugun":  (35.50, 138.78),    # Fuji Five Lakes
    "waga_gun":        (39.40, 140.75),
    "higashiokitamagun": (38.00, 140.00),
    "nasugun":         (37.02, 140.12),
    "shioya_gun":      (36.78, 139.85),
    "ono_gun":         (36.13, 137.30),
}

def geocode_city(slug, pref_display, cache):
    key = f"{pref_display}:{slug}"
    if key in cache:
        return cache[key]
    if slug in GUN_OVERRIDES:
        la, lo = GUN_OVERRIDES[slug]
        cache[key] = [la, lo, "manual"]
        json.dump(cache, open(GEO_CACHE, "w"))
        return cache[key]
    # slug → query variants, most-specific first
    name = slug.replace("_", " ").strip()
    variants = [f"{name}, {pref_display}, Japan"]
    for suffix in ("gun", "shi", "machi", "mura"):
        if name.endswith(suffix) and len(name) > len(suffix) + 2:
            stem = name[: -len(suffix)].strip()
            variants += [f"{stem}, {pref_display}, Japan",
                         f"{stem} District, {pref_display}, Japan"]
            break
    for q in variants:
        body = curl("https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" +
                    urllib.parse.quote(q), timeout=20)
        time.sleep(1.1)  # Nominatim rate limit
        try:
            j = json.loads(body)
        except Exception:
            continue
        if j:
            cache[key] = [round(float(j[0]["lat"]), 5), round(float(j[0]["lon"]), 5), "osm"]
            json.dump(cache, open(GEO_CACHE, "w"))
            return cache[key]
    cache[key] = None
    json.dump(cache, open(GEO_CACHE, "w"))
    return None


def main():
    # optional argv: prefecture slugs to (re)scrape — appends to existing output
    only = set(sys.argv[1:])
    out, seen = [], set()
    if only and os.path.exists("/tmp/suumo_mountain.json"):
        out = json.load(open("/tmp/suumo_mountain.json"))
        out = [r for r in out if r.get("_pref_slug") not in only]
        seen = {r["url"].rsplit("nc_", 1)[-1].rstrip("/") for r in out}
        print(f"appending to {len(out)} existing rows", file=sys.stderr)
    cache = geo_cache()
    curl("https://suumo.jp/")
    for pref, (display, plat, plng, keep) in PREFS.items():
        if only and pref not in only:
            continue
        idx = curl(f"https://suumo.jp/tochi/{pref}/")
        slugs = sorted(set(SC_RE.findall(idx)))
        if keep:
            slugs = [s for s in slugs if any(k in s for k in keep)]
        print(f"{display}: {len(slugs)} cities", file=sys.stderr)
        for city in slugs:
            geo = geocode_city(city, display, cache)
            clat, clng, gsrc = (geo[0], geo[1], geo[2]) if geo else (plat, plng, "pref")
            for pg in range(1, 6):
                url = f"https://suumo.jp/tochi/{pref}/sc_{city}/" + (f"?page={pg}" if pg > 1 else "")
                h = curl(url)
                if len(h) < 5000:
                    break
                positions = [(m.start(), m.group(3)) for m in URL_RE.finditer(h)]
                ids_pg, uniq = set(), []
                for pos, aid in positions:
                    if aid not in ids_pg:
                        ids_pg.add(aid)
                        uniq.append((pos, aid))
                n0 = len(out)
                for i, (pos, aid) in enumerate(uniq):
                    if aid in seen:
                        continue
                    end = uniq[i + 1][0] if i + 1 < len(uniq) else pos + 3500
                    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h[pos:end]))
                    price, area = parse_price(txt), parse_area(txt)
                    if not price or not area or price < 100000 or area < 150:
                        continue
                    seen.add(aid)
                    out.append({
                        "_pref_slug": pref,
                        "pref": display, "city": city,
                        "m2": round(area, 1),
                        "price_jpy": price,
                        "usd": round(price * JPYUSD),
                        "lat": clat, "lng": clng, "geocode_src": gsrc,
                        "url": f"https://suumo.jp/tochi/{pref}/sc_{city}/nc_{aid}/",
                    })
                if len(out) == n0 and pg > 1:
                    break
                time.sleep(0.5)
        json.dump(out, open("/tmp/suumo_mountain.json", "w"))
        print(f"  running total: {len(out)}", file=sys.stderr)
    json.dump(out, open("/tmp/suumo_mountain.json", "w"))
    print(f"TOTAL {len(out)} rows -> /tmp/suumo_mountain.json", file=sys.stderr)


if __name__ == "__main__":
    main()
