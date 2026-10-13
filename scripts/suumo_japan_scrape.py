"""SUUMO — all-Japan land + used houses, and Tokyo used apartments.

Kinds (each card is parsed straight off SUUMO list pages, no detail fetches):
  land       /tochi/<pref>/sc_<city>/          all 47 prefectures
  house      /chukoikkodate/<pref>/sc_<city>/  all 47 prefectures (akiya-style homes)
  apartment  /ms/chuko/tokyo/sc_<city>/        Tokyo (deeper on the 23 wards)
Cards give price, address, nearest station + walk minutes, land / building /
floor area, layout (e.g. 3LDK) and build year. Crawled with a small thread
pool, then geocoded by address with the national GSI address-search API
(neighbourhood-level, cached in scripts/geo_cache_jp.json).
Emits /tmp/suumo_japan.json for suumo_japan_merge.py.

Usage: python3 suumo_japan_scrape.py [kinds]   e.g. "land,house,apartment"
"""
import json, os, re, subprocess, sys, threading, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
OUT = "/tmp/suumo_japan.json"
GEO_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geo_cache_jp.json")
KINDS = (sys.argv[1] if len(sys.argv) > 1 else "land,house,apartment").split(",")

PREFS = ("aichi akita aomori chiba ehime fukui fukuoka fukushima gifu gumma hiroshima hokkaido_ "
         "hyogo ibaraki ishikawa iwate kagawa kagoshima kanagawa kochi kumamoto kyoto mie miyagi "
         "miyazaki nagano nagasaki nara niigata oita okayama okinawa osaka saga saitama shiga "
         "shimane shizuoka tochigi tokushima tokyo tottori toyama wakayama yamagata yamaguchi "
         "yamanashi").split()
WARDS = set("chiyoda chuo minato shinjuku bunkyo taito sumida koto shinagawa meguro ota setagaya "
            "shibuya nakano suginami toshima kita arakawa itabashi nerima adachi katsushika edogawa".split())
BASE = {"land": "tochi/{p}", "house": "chukoikkodate/{p}", "apartment": "ms/chuko/{p}"}
PAGES = {"land": 3, "house": 2, "apartment": 3}
WARD_PAGES = 8
SC_RE = re.compile(r"sc_([a-z_0-9]+)")

def curl(url, timeout=30):
    for attempt in range(2):
        try:
            out = subprocess.run(["curl", "-sL", "-m", str(timeout), "-A", UA,
                                  "-H", "Accept-Language: ja,en;q=0.8", "-H", "Referer: https://suumo.jp/", url],
                                 capture_output=True, text=True, timeout=timeout + 5).stdout
            if out: return out
        except Exception:
            pass
        time.sleep(1.5)
    return ""

# ---------- card parsing ----------
def jnum(s):
    try: return float(s.replace(",", ""))
    except Exception: return None

def parse_price(t):
    m = re.search(r"販売価格[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)\s*億\s*([0-9,]{1,6})?\s*万?円?", t)
    if m and "億" in m.group(0):
        return int(float(m.group(1)) * 1e8 + (jnum(m.group(2) or "0") or 0) * 1e4)
    m = re.search(r"販売価格[^0-9]{0,8}([0-9]{1,5}(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*万円", t)
    return int((jnum(m.group(1)) or 0) * 10000) if m else None

def area(label, t):
    m = re.search(label + r"\s*([0-9,]+(?:\.[0-9]+)?)\s*(?:m\s*2|㎡|平米)", t)
    return jnum(m.group(1)) if m else None

SEA = re.compile(r"海が見え|海一望|オーシャンビュー|海まで徒歩|海近|海を望|海を見渡|海側|海辺|ビーチ")

def parse_cards(html, kind, pref, city):
    pat = {"land": r"/tochi/[a-z_]+/sc_[a-z_0-9]+/nc_(\d+)/",
           "house": r"/chukoikkodate/[a-z_]+/sc_[a-z_0-9]+/nc_(\d+)/",
           "apartment": r"/ms/chuko/[a-z_]+/sc_[a-z_0-9]+/nc_(\d+)/"}[kind]
    first = {}
    for m in re.finditer(pat, html):
        first.setdefault(m.group(1), (m.start(), m.group(0)))
    items = sorted(first.items(), key=lambda kv: kv[1][0])
    out = []
    for i, (nid, (pos, path)) in enumerate(items):
        end = items[i + 1][1][0] if i + 1 < len(items) else pos + 5000
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html[pos:end]))
        price = parse_price(t)
        if not price or price < 300000:
            continue
        land, bldg, floor = area("土地面積", t), area("建物面積", t), area("専有面積", t)
        size = floor if kind == "apartment" else (bldg if kind == "house" else land)
        if not size or size < (12 if kind == "apartment" else 30):
            continue
        st = re.search(r"「([^」]{1,20})」\s*(?:徒歩|歩)\s*(\d+)\s*分", t)
        lay = re.search(r"間取り\s*([0-9]+\s*[SLDKR]+|ワンルーム|[0-9]+K)", t)
        yr = re.search(r"築年月\s*(\d{4})\s*年", t)
        ad = re.search(r"所在地\s*(.+?)\s*(?:沿線|交通)", t)
        nm = re.search(r"物件名\s*(.+?)\s*販売価格", t)
        out.append({
            "id": nid, "kind": kind, "url": "https://suumo.jp" + path, "pref": pref, "city": city,
            "name": (nm.group(1) if nm else "")[:80], "price_jpy": price,
            "land_m2": land, "bldg_m2": bldg, "floor_m2": floor, "size_m2": size,
            "layout": re.sub(r"\s+", "", lay.group(1)) if lay else None,
            "year": int(yr.group(1)) if yr else None,
            "addr": (ad.group(1) if ad else "")[:80],
            "station": st.group(1) if st else None, "walk_min": int(st.group(2)) if st else None,
            "sea_hint": bool(SEA.search(t)),
        })
    return out

# ---------- crawl ----------
lock = threading.Lock()
rows = {}
if os.path.exists(OUT):
    for r in json.load(open(OUT)):
        rows[r["url"]] = r

def crawl(task):
    kind, pref, city, pages = task
    got = 0
    base = f"https://suumo.jp/{BASE[kind].format(p=pref)}/sc_{city}/"
    for pg in range(1, pages + 1):
        recs = parse_cards(curl(base + (f"?page={pg}" if pg > 1 else "")), kind, pref, city)
        if not recs:
            break
        with lock:
            new = [r for r in recs if r["url"] not in rows]
            for r in new: rows[r["url"]] = r
        got += len(new)
        if not new or len(recs) < 15:
            break
        time.sleep(0.4)
    return got

def city_slugs(kind, pref):
    idx = curl(f"https://suumo.jp/{BASE[kind].format(p=pref)}/")
    return sorted(set(SC_RE.findall(idx)))

def main():
    tasks = []
    for kind in KINDS:
        prefs = ["tokyo"] if kind == "apartment" else PREFS
        for pref in prefs:
            for city in city_slugs(kind, pref):
                pages = WARD_PAGES if (kind == "apartment" and city in WARDS) else PAGES[kind]
                tasks.append((kind, pref, city, pages))
        print(f"{kind}: {sum(1 for t in tasks if t[0]==kind)} city tasks", file=sys.stderr)
    done = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for _ in ex.map(crawl, tasks):
            done += 1
            if done % 100 == 0:
                with lock:
                    json.dump(list(rows.values()), open(OUT, "w"))
                print(f"  {done}/{len(tasks)} tasks · {len(rows)} rows", file=sys.stderr)
    json.dump(list(rows.values()), open(OUT, "w"))
    geocode_all()

# ---------- geocode (GSI) ----------
def norm_addr(a):
    a = re.sub(r"[0-9０-９\-－−ー‐ー番地号の丁目]+$", "", (a or "").strip())
    return a.strip()

def gsi(q):
    body = curl("https://msearch.gsi.go.jp/address-search/AddressSearch?q=" + urllib.parse.quote(q), timeout=15)
    try:
        j = json.loads(body)
        if j:
            lon, lat = j[0]["geometry"]["coordinates"]
            return [round(lat, 5), round(lon, 5)]
    except Exception:
        pass
    return None

def geocode_all():
    cache = json.load(open(GEO_CACHE)) if os.path.exists(GEO_CACHE) else {}
    want = sorted({norm_addr(r["addr"]) for r in rows.values() if norm_addr(r["addr"])} - set(cache))
    print(f"geocoding {len(want)} new addresses (cache {len(cache)})", file=sys.stderr)
    def one(a):
        g = gsi(a)
        if not g:  # trim progressively to the municipality
            m = re.match(r"(.+?[都道府県].+?[市区町村郡])", a)
            if m: g = gsi(m.group(1))
        return a, g
    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, (a, g) in enumerate(ex.map(one, want), 1):
            cache[a] = g
            if i % 500 == 0:
                json.dump(cache, open(GEO_CACHE, "w"), ensure_ascii=False)
                print(f"  geocoded {i}/{len(want)}", file=sys.stderr)
    json.dump(cache, open(GEO_CACHE, "w"), ensure_ascii=False)
    hit = 0
    for r in rows.values():
        g = cache.get(norm_addr(r["addr"]))
        if g: r["lat"], r["lng"] = g; hit += 1
    json.dump(list(rows.values()), open(OUT, "w"))
    from collections import Counter
    print(f"TOTAL {len(rows)} rows ({hit} geocoded) {dict(Counter(r['kind'] for r in rows.values()))} -> {OUT}", file=sys.stderr)

if __name__ == "__main__":
    main()
