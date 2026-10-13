"""Weekly scanner — scrape all five countries' coastal land sources,
score each listing, and emit data/latest.csv + data/new_high.json.

Sources: FazWaz + dotproperty (Thailand), realestate.co.nz API (NZ),
REW (BC), Mudah (Malaysia), SUUMO (Japan).

Designed to be robust to flaky sites: per-source try/except, polite delays.
"""
from __future__ import annotations
import csv, json, os, re, subprocess, sys, time, pathlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from score import rate  # noqa: E402

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def curl(url: str, extra_headers: list[str] | None = None, timeout: int = 35) -> str:
    cmd = ["curl", "-sSL", "-m", str(timeout), "-A", UA,
           "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "-H", "Accept-Language: en-US,en;q=0.9"]
    for h in extra_headers or []:
        cmd.extend(["-H", h])
    cmd.append(url)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5).stdout
    except subprocess.TimeoutExpired:
        return ""


def scrape_fazwaz_th() -> list[dict]:
    out = []
    for slug in ("krabi", "phuket", "phang-nga", "trang"):
        for pg in range(1, 6):
            url = f"https://www.fazwaz.com/land-for-sale-with-sea-view/thailand/{slug}" + (
                f"?page={pg}" if pg > 1 else ""
            )
            h = curl(url)
            blocks = re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', h, re.S)
            n0 = len(out)
            for b in blocks:
                try:
                    d = json.loads(b)
                except json.JSONDecodeError:
                    continue
                items = d if isinstance(d, list) else [d]
                for o in items:
                    if not isinstance(o, dict) or "geo" not in o or not o.get("url"):
                        continue
                    geo = o["geo"]
                    name = o.get("name", "")
                    m = re.search(r"(\d+)\s*Rai", name, re.I)
                    rai = float(m.group(1)) if m else None
                    usd = None
                    pm = re.search(r"\$([0-9,]+)", name)
                    if pm:
                        usd = int(pm.group(1).replace(",", ""))
                    if not (rai and usd):
                        continue
                    m2 = rai * 1600
                    out.append({
                        "country": "Thailand",
                        "region": "Krabi/Andaman",
                        "area": (o.get("url", "").split("-in-")[-1].split("-")[0] or "")[:30],
                        "m2": round(m2),
                        "acres": round(m2 / 4046.86, 2),
                        "view": "sea_visible",  # set by source filter
                        "elev_m": "",
                        "price_local": usd,
                        "currency": "USD",
                        "price_usd": usd,
                        "usd_per_m2": round(usd / m2, 2),
                        "usd_per_acre": round(usd / (m2 / 4046.86)),
                        "title": "",
                        "source": "fazwaz",
                        "listing_link": o["url"],
                    })
            if len(out) == n0 and pg > 1:
                break
            time.sleep(0.4)
    return out


def scrape_realestate_nz() -> list[dict]:
    """Use realestate.co.nz internal JSON:API endpoint."""
    out = []
    base = "https://platform.realestate.co.nz/search/v1/listings"
    headers = ["Accept: application/json", "Referer: https://www.realestate.co.nz/"]
    for cat in ("rural_sale", "res_sale"):
        off = 0
        for _ in range(20):  # cap pages per category
            url = f"{base}?filter%5Bcategory%5D%5B%5D={cat}&page%5Blimit%5D=100&page%5Boffset%5D={off}"
            txt = curl(url, headers)
            try:
                d = json.loads(txt)
            except json.JSONDecodeError:
                break
            data = d.get("data", [])
            if not data:
                break
            for it in data:
                a = it.get("attributes", {})
                ad = a.get("address", {})
                try:
                    lat = float(ad.get("latitude"))
                    lon = float(ad.get("longitude"))
                except (TypeError, ValueError):
                    continue
                fa = a.get("floor-area") or 0
                if fa and fa > 0:
                    continue
                pd = a.get("price-display") or ""
                pm = re.search(r"\$([0-9][0-9,]{3,})", pd)
                if not pm:
                    continue
                nzd = int(pm.group(1).replace(",", ""))
                la = a.get("land-area")
                if not la:
                    continue
                unit = (a.get("land-area-unit") or "").upper()
                m2 = la * 10000 if unit == "HA" else (la * 4046.86 if "ACRE" in unit else la)
                if m2 < 800:
                    continue
                usd = nzd * 0.60
                slug = a.get("website-slug") or ""
                out.append({
                    "country": "New Zealand",
                    "region": (ad.get("region-slug") or "").replace("-", " ").title(),
                    "area": (ad.get("district-slug") or "").replace("-", " ").title(),
                    "m2": round(m2),
                    "acres": round(m2 / 4046.86, 2),
                    "view": "coastal",  # filter further with geo if needed
                    "elev_m": "",
                    "price_local": nzd,
                    "currency": "NZD",
                    "price_usd": round(usd),
                    "usd_per_m2": round(usd / m2, 2),
                    "usd_per_acre": round(usd / (m2 / 4046.86)),
                    "title": "Freehold",
                    "source": "realestate.co.nz",
                    "listing_link": "https://www.realestate.co.nz" + slug,
                })
            off += 100
            if off >= d.get("meta", {}).get("totalResults", 0):
                break
            time.sleep(0.2)
    return out


def scrape_rew_bc() -> list[dict]:
    """REW coastal BC, list pages give JSON-LD geo+url, detail pages give price+size."""
    areas = ("vancouver-island-bc", "sunshine-coast-bc", "powell-river-bc")
    found: dict[str, tuple[float, float, str]] = {}
    for area in areas:
        for pg in range(1, 16):
            url = f"https://www.rew.ca/properties/areas/{area}/type/land-lot" + (
                f"?page={pg}" if pg > 1 else ""
            )
            h = curl(url, ["Upgrade-Insecure-Requests: 1"])
            n0 = len(found)
            for b in re.findall(r'application/ld\+json[^>]*>(.*?)</script>', h, re.S):
                try:
                    d = json.loads(b)
                except json.JSONDecodeError:
                    continue
                for o in (d if isinstance(d, list) else [d]):
                    if not isinstance(o, dict) or "geo" not in o or not o.get("url"):
                        continue
                    g = o["geo"]
                    try:
                        found[o["url"]] = (float(g["latitude"]), float(g["longitude"]), o.get("name", "")[:80])
                    except (KeyError, ValueError):
                        pass
            if len(found) == n0 and pg > 1:
                break
            time.sleep(0.3)
    out = []
    for url, (lat, lon, name) in found.items():
        for attempt in range(3):
            h = curl(url, ["Upgrade-Insecure-Requests: 1"])
            if "Just a moment" not in h and len(h) > 8000:
                break
            time.sleep(2 + attempt * 2)
        pr = re.search(r"\$([0-9]{2,3}(?:,[0-9]{3})+)", h)
        # Anchor size extraction to the "Lot Size" label, NOT the description body
        # (descriptions often contain misleading text like "48-acre development").
        ls_match = re.search(r"Lot Size.{0,300}", h, re.S)
        m2 = None
        if ls_match:
            ls_text = re.sub(r"<[^>]+>", " ", ls_match.group(0))[:200]
            sqft = re.search(r"\(?([0-9][0-9,]*)\s*ft(?:&sup2;|²|2)\)?", ls_text)
            acre = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*ac\b", ls_text, re.I)
            if sqft:
                m2 = int(sqft.group(1).replace(",", "")) * 0.092903
            elif acre:
                m2 = float(acre.group(1).replace(",", "")) * 4046.86
        if not pr or not m2:
            continue
        cad = int(pr.group(1).replace(",", ""))
        if m2 < 300 or m2 > 1_500_000 or cad < 50000:
            continue
        usd = cad * 0.73
        area_name = name.split(",")[1].strip() if "," in name else ""
        out.append({
            "country": "British Columbia",
            "region": "BC",
            "area": area_name[:40],
            "m2": round(m2),
            "acres": round(m2 / 4046.86, 2),
            "view": "coastal",
            "elev_m": "",
            "price_local": cad,
            "currency": "CAD",
            "price_usd": round(usd),
            "usd_per_m2": round(usd / m2, 2),
            "usd_per_acre": round(usd / (m2 / 4046.86)),
            "title": "Freehold",
            "source": "REW",
            "listing_link": url,
        })
    return out


def scrape_mudah_my() -> list[dict]:
    states = ("penang", "kedah", "johor", "pahang", "terengganu",
              "kelantan", "sabah", "sarawak", "melaka")
    URL_RE = re.compile(r"https?://www\.mudah\.my/[a-z0-9\-]+-(\d{8,10})\.htm")
    CARS = re.compile(r"\b(toyota|honda|mazda|nissan|mercedes|bmw|lexus|isuzu|perodua|proton|kawasaki|yamaha|suzuki|ducati|hyundai|ford|volvo|porsche|audi|mitsubishi|civic|yaris|altis|fortuner)\b", re.I)
    out = []
    seen_ids: set[str] = set()
    curl("https://www.mudah.my/", ["Referer: https://www.mudah.my/"])
    time.sleep(2)
    for st in states:
        for pg in range(1, 8):
            url = f"https://www.mudah.my/{st}/lands+for+sale" + (
                f"?o={pg}" if pg > 1 else ""
            )
            h = curl(url, ["Referer: https://www.mudah.my/"])
            if "Just a moment" in h or len(h) < 20000:
                time.sleep(6)
                h = curl(url, ["Referer: https://www.mudah.my/"])
            positions = [(m.start(), m.group(0), m.group(1)) for m in URL_RE.finditer(h)]
            uniq: list[tuple[int, str, str]] = []
            seen_pg: set[str] = set()
            for pos, u, aid in positions:
                if aid in seen_pg:
                    continue
                seen_pg.add(aid)
                uniq.append((pos, u, aid))
            n0 = len(out)
            for i, (pos, u, aid) in enumerate(uniq):
                if aid in seen_ids:
                    continue
                if CARS.search(u):
                    continue
                end = uniq[i + 1][0] if i + 1 < len(uniq) else pos + 4000
                chunk = h[pos:end]
                txt = re.sub(r"<[^>]+>", " ", chunk)
                txt = re.sub(r"\s+", " ", txt)
                pr = re.search(r"RM\s*([0-9]{1,3}(?:,[0-9]{3})+)", txt)
                sz = re.search(r"([0-9][0-9,]*)\s*(sq\.?\s?ft|sqft|acres?|hectares?)", txt, re.I)
                if not pr or not sz:
                    continue
                rm = int(pr.group(1).replace(",", ""))
                if rm < 50000:
                    continue
                val = float(sz.group(1).replace(",", ""))
                unit = sz.group(2).lower().replace(".", "").replace(" ", "")
                if "sqft" in unit:
                    m2 = val * 0.092903
                elif "acre" in unit:
                    m2 = val * 4046.86
                elif "hectare" in unit:
                    m2 = val * 10000
                else:
                    m2 = val
                if m2 < 100:
                    continue
                usd = rm * 0.21
                seen_ids.add(aid)
                out.append({
                    "country": "Malaysia",
                    "region": st.title(),
                    "area": "",
                    "m2": round(m2),
                    "acres": round(m2 / 4046.86, 2),
                    "view": "coastal",
                    "elev_m": "",
                    "price_local": rm,
                    "currency": "MYR",
                    "price_usd": round(usd),
                    "usd_per_m2": round(usd / m2, 2),
                    "usd_per_acre": round(usd / (m2 / 4046.86)),
                    "title": "",
                    "source": "Mudah",
                    "listing_link": u,
                })
            if len(out) == n0 and pg > 1:
                break
            time.sleep(4)
    return out


def scrape_suumo_jp() -> list[dict]:
    coastal = {
        "chiba":     ["minamiboso","tateyama","kamogawa","isumi","futtsu","kyonan","onjuku","ichinomiya","katsuura"],
        "shizuoka":  ["ito","atami","izu","shimoda","kawazu","numazu","matsuzaki","higashiizu","minamiizu","mishima"],
        "kanagawa":  ["hayama","miura","kamakura","zushi","yokosuka","fujisawa"],
        "wakayama":  ["shirahama","kushimoto","kainan","tanabe","susami","wakayama"],
        "okinawa":   ["nago","motobu","ishigaki","miyakojima","onna","nanjo","itoman","kunigami","ogimi"],
        "miyazaki":  ["nichinan","hyuga","miyazaki","nobeoka","kushima","saito"],
        "niigata":   ["joetsu","kashiwazaki","itoigawa","sado","murakami","niigata","nagaoka"],
        "hokkaido_": ["hakodate","otaru","muroran","kushiro","tomakomai","abashiri","wakkanai","obihiro","chitose","ishikari","asahikawa"],
        "fukuoka":   ["itoshima","fukuoka","munakata","kitakyushu","fukutsu","koga"],
        "nagasaki":  ["sasebo","nagasaki","omura","hirado","goto","saikai","unzen","minamishimabara"],
        "kagoshima": ["ibusuki","kanoya","amami","satsumasendai","kagoshima","minamikyushu","tarumizu","makurazaki"],
        "kumamoto":  ["amakusa","ashikita","minamata","yatsushiro","uki","kamiamakusa"],
        "oita":      ["oita","beppu","kunisaki","saiki","bungoono","usuki","tsukumi"],
        "ehime":     ["matsuyama","uwajima","yawatahama","ozu","ainan","ikata","seiyo"],
        "kochi":     ["kochi","tosashimizu","sukumo","susaki","aki","muroto","nahari","kuroshio"],
        "mie":       ["shima","toba","owase","ise","kumano","minamiise","kihoku"],
        "hyogo":     ["awaji","sumoto","minamiawaji","ako","tatsuno","akashi"],
        "tottori":   ["tottori","sakaiminato","yonago","kurayoshi"],
        "shimane":   ["matsue","izumo","masuda","hamada","oda","gotsu"],
        "yamaguchi": ["shimonoseki","hagi","hofu","ube","yanai","suo_oshima","nagato"],
        "aichi":     ["chita","tahara","gamagori","minamichita","minamishitara"],
        "aomori":    ["hachinohe","mutsu","aomori","tsugaru"],
        "iwate":     ["kamaishi","miyako","ofunato","rikuzentakata","yamada","ohtsuchi"],
        "miyagi":    ["ishinomaki","kesennuma","shiogama","minamisanriku","onagawa","watari","yamamoto"],
        "akita":     ["oga","akita","yurihonjo","nikaho"],
        "yamagata":  ["tsuruoka","sakata","yuza"],
        "fukushima": ["iwaki","soma","minamisoma","hirono","naraha"],
        "ibaraki":   ["kashima","oarai","hitachi","kitaibaraki","takahagi"],
        "saga":      ["karatsu","imari","ureshino","genkai"],
        "tokushima": ["minami","mugi","naruto","tokushima","kaiyo","kainan"],
        "kagawa":    ["takamatsu","sanuki","shodoshima","tonosho","sakaide"],
        "hiroshima": ["kure","onomichi","fukuyama","etajima","mihara"],
        "okayama":   ["kasaoka","setouchi","tamano","bizen","ushimado"],
    }
    URL_RE = re.compile(r"/tochi/([a-z]+)/sc_([a-z_]+)/nc_(\d+)/")

    def parse_price(t: str) -> int | None:
        m = re.search(r"販売価格[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)\s*億\s*([0-9]{1,5})?\s*万円", t)
        if m:
            e = float(m.group(1))
            ma = int(m.group(2)) if m.group(2) else 0
            return int(e * 1e8 + ma * 1e4)
        m = re.search(r"販売価格[^0-9]{0,8}([0-9]{1,5}(?:,[0-9]{3})*)\s*万円", t)
        if m:
            return int(m.group(1).replace(",", "")) * 10000
        return None

    def parse_area(t: str) -> float | None:
        for pat in (r"土地面積\s*([0-9,]+(?:\.[0-9]+)?)\s*m\s*2",
                    r"土地面積\s*([0-9,]+(?:\.[0-9]+)?)\s*㎡",
                    r"土地面積\s*([0-9,]+(?:\.[0-9]+)?)\s*平米"):
            m = re.search(pat, t)
            if m:
                return float(m.group(1).replace(",", ""))
        return None

    out = []
    seen: set[str] = set()
    curl("https://suumo.jp/", ["Referer: https://suumo.jp/"])
    time.sleep(1)
    JPYUSD = 0.0064
    for pref, cities in coastal.items():
        for city in cities:
            for pg in range(1, 5):
                url = f"https://suumo.jp/tochi/{pref}/sc_{city}/" + (f"?page={pg}" if pg > 1 else "")
                h = curl(url, ["Referer: https://suumo.jp/"])
                if len(h) < 5000:
                    break
                positions = [(m.start(), m.group(3)) for m in URL_RE.finditer(h)]
                ids_pg: set[str] = set()
                uniq: list[tuple[int, str]] = []
                for pos, aid in positions:
                    if aid in ids_pg:
                        continue
                    ids_pg.add(aid)
                    uniq.append((pos, aid))
                n0 = len(out)
                for i, (pos, aid) in enumerate(uniq):
                    if aid in seen:
                        continue
                    end = uniq[i + 1][0] if i + 1 < len(uniq) else pos + 3500
                    chunk = h[pos:end]
                    txt = re.sub(r"<[^>]+>", " ", chunk)
                    txt = re.sub(r"\s+", " ", txt)
                    price = parse_price(txt)
                    area = parse_area(txt)
                    if not price or not area or price < 100000 or area < 100:
                        continue
                    seen.add(aid)
                    usd = price * JPYUSD
                    out.append({
                        "country": "Japan",
                        "region": pref.title(),
                        "area": city.title(),
                        "m2": round(area, 1),
                        "acres": round(area / 4046.86, 2),
                        "view": "coastal",
                        "elev_m": "",
                        "price_local": price,
                        "currency": "JPY",
                        "price_usd": round(usd),
                        "usd_per_m2": round(usd / area, 2),
                        "usd_per_acre": round(usd / (area / 4046.86)),
                        "title": "",
                        "source": "SUUMO",
                        "listing_link": f"https://suumo.jp/tochi/{pref}/sc_{city}/nc_{aid}/",
                    })
                if len(out) == n0 and pg > 1:
                    break
                time.sleep(0.6)
    return out


def listing_id(row: dict) -> str:
    """Stable identifier for dedup across runs."""
    return row.get("listing_link", "")


def main() -> int:
    sources = [
        ("Thailand", scrape_fazwaz_th),
        ("New Zealand", scrape_realestate_nz),
        ("British Columbia", scrape_rew_bc),
        ("Malaysia", scrape_mudah_my),
        ("Japan", scrape_suumo_jp),
    ]
    all_rows: list[dict] = []
    for name, fn in sources:
        try:
            rs = fn()
            print(f"{name}: {len(rs)} listings", flush=True)
            all_rows.extend(rs)
        except Exception as e:  # one source failing shouldn't kill the run
            print(f"{name} ERROR: {e}", file=sys.stderr, flush=True)

    for r in all_rows:
        rate(r)

    # Output latest.csv
    cols = ["rating", "country", "region", "area", "m2", "acres", "view", "elev_m",
            "price_local", "currency", "price_usd", "usd_per_m2", "usd_per_acre",
            "title", "source", "rating_breakdown", "listing_link"]
    latest = DATA / "latest.csv"
    with latest.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(all_rows, key=lambda x: -x["rating"]):
            w.writerow(r)

    # Diff against seen.json — identify NEW high-rated
    seen_path = DATA / "seen.json"
    seen = set()
    if seen_path.exists():
        try:
            seen = set(json.loads(seen_path.read_text()))
        except json.JSONDecodeError:
            seen = set()
    # Listings rated >=80 trigger a "do further due diligence" issue.
    DD_THRESHOLD = int(os.environ.get("DD_THRESHOLD", "80"))
    new_dd = [r for r in all_rows if r["rating"] >= DD_THRESHOLD and listing_id(r) not in seen]
    print(f"TOTAL: {len(all_rows)} | new DD candidates (>={DD_THRESHOLD}, unseen): {len(new_dd)}", flush=True)

    (DATA / "new_high.json").write_text(json.dumps(new_dd, indent=2))

    # Update seen
    new_seen = seen | {listing_id(r) for r in all_rows}
    seen_path.write_text(json.dumps(sorted(new_seen)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
