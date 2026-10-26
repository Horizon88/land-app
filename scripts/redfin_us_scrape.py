"""Redfin: US oceanfront and ski-town land + homes.

Same gis-csv export as redfin_ma_scrape.py (open, accepts a polygon, 350 rows per
query, tiles split when they hit the cap), run over a list of coastal and ski
regions. Pulls vacant land and homes (single-family, condo, townhouse).
Emits /tmp/redfin_us.json for redfin_us_merge.py.

Usage: python3 scripts/redfin_us_scrape.py [region-substring ...]
"""
import csv, io, json, subprocess, sys, time, urllib.parse
from collections import Counter

RELAY = "https://landrelay.flag-theory.workers.dev"
OUT = "/tmp/redfin_us.json"
CAP = 350
KINDS = [("5", "land"), ("1,2,3", "house")]

# name, kind (coast/ski), bbox (west, south, east, north)
REGIONS = [
    # --- ski towns
    ("Park City UT", "ski", (-111.60, 40.58, -111.40, 40.72)),
    ("Ogden Valley UT (Powder Mtn/Snowbasin)", "ski", (-111.95, 41.20, -111.70, 41.40)),
    ("Jackson Hole WY", "ski", (-110.95, 43.40, -110.70, 43.65)),
    ("Sun Valley-Ketchum ID", "ski", (-114.45, 43.60, -114.25, 43.76)),
    ("Big Sky MT", "ski", (-111.45, 45.20, -111.20, 45.32)),
    ("Whitefish MT", "ski", (-114.45, 48.33, -114.25, 48.53)),
    ("Vail-Beaver Creek CO", "ski", (-106.65, 39.58, -106.25, 39.67)),
    ("Aspen-Snowmass CO", "ski", (-107.00, 39.15, -106.75, 39.25)),
    ("Breckenridge-Keystone CO", "ski", (-106.15, 39.45, -105.90, 39.65)),
    ("Steamboat Springs CO", "ski", (-106.90, 40.40, -106.75, 40.55)),
    ("Telluride CO", "ski", (-107.95, 37.88, -107.75, 37.98)),
    ("Crested Butte CO", "ski", (-107.05, 38.82, -106.90, 38.93)),
    ("Taos Ski Valley NM", "ski", (-105.60, 36.48, -105.40, 36.62)),
    ("Lake Tahoe-Truckee CA/NV", "ski", (-120.30, 38.90, -119.90, 39.35)),
    ("Mammoth Lakes CA", "ski", (-119.10, 37.60, -118.90, 37.70)),
    ("Stowe VT", "ski", (-72.80, 44.42, -72.62, 44.55)),
    ("Killington-Okemo VT", "ski", (-72.85, 43.55, -72.65, 43.72)),
    ("Mad River Valley VT", "ski", (-72.95, 44.10, -72.75, 44.22)),
    ("North Conway NH", "ski", (-71.25, 43.95, -71.05, 44.12)),
    ("Bend-Mt Bachelor OR", "ski", (-121.45, 43.95, -121.20, 44.12)),
    ("Mt Hood OR", "ski", (-121.85, 45.25, -121.65, 45.35)),
    ("Sandpoint ID", "ski", (-116.65, 48.20, -116.45, 48.40)),
    # --- ocean
    ("Midcoast Maine", "coast", (-69.80, 43.75, -68.95, 44.30)),
    ("Mount Desert Island ME", "coast", (-68.45, 44.20, -68.15, 44.45)),
    ("Outer Cape Cod MA", "coast", (-70.10, 41.65, -69.90, 42.08)),
    ("Martha's Vineyard MA", "coast", (-70.85, 41.30, -70.45, 41.50)),
    ("Narragansett Bay RI", "coast", (-71.45, 41.43, -71.10, 41.78)),
    ("North Fork NY", "coast", (-72.60, 40.95, -72.20, 41.15)),
    ("Outer Banks NC", "coast", (-75.85, 35.20, -75.45, 36.30)),
    ("Charleston islands SC", "coast", (-80.15, 32.55, -79.70, 32.85)),
    ("Hilton Head SC", "coast", (-80.85, 32.10, -80.65, 32.25)),
    ("Emerald Coast-30A FL", "coast", (-86.55, 30.28, -85.95, 30.42)),
    ("Orange Beach AL", "coast", (-87.80, 30.20, -87.50, 30.30)),
    ("Florida Keys", "coast", (-81.85, 24.50, -80.30, 25.20)),
    ("Oregon North Coast", "coast", (-124.10, 44.90, -123.90, 45.95)),
    ("San Juan Islands WA", "coast", (-123.25, 48.40, -122.75, 48.75)),
    ("Big Sur-Carmel CA", "coast", (-121.95, 36.20, -121.70, 36.60)),
    ("Kona-Kohala HI", "coast", (-156.10, 19.40, -155.80, 20.10)),
    ("Maui west+south HI", "coast", (-156.70, 20.55, -156.25, 21.05)),
    ("Kauai north shore HI", "coast", (-159.60, 22.10, -159.30, 22.25)),
]

def relay(url, timeout=40):
    try:
        return subprocess.run(["curl", "-sk", "--compressed", "-m", str(timeout),
                               f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"],
                              capture_output=True, text=True, timeout=timeout + 5).stdout
    except Exception:
        return ""

def poly(w, s, e, n):
    return f"{w} {s},{e} {s},{e} {n},{w} {n},{w} {s}"

def pull(uipt, box):
    url = ("https://www.redfin.com/stingray/api/gis-csv?al=1&num_homes=350"
           "&ord=redfin-recommended-asc&page_number=1&sf=1,2,3,5,6,7&status=9"
           f"&uipt={uipt}&v=8&poly={urllib.parse.quote(poly(*box))}")
    for attempt in range(2):
        body = relay(url)
        lines = [l for l in body.splitlines() if l and not l.startswith('"In accordance')]
        if lines and lines[0].startswith("SALE TYPE"):
            return list(csv.DictReader(io.StringIO("\n".join(lines))))
        time.sleep(2)
    return []

def pull_tiled(uipt, box, depth=0):
    rows = pull(uipt, box)
    time.sleep(0.4)
    if len(rows) >= CAP - 5 and depth < 4:
        w, s, e, n = box; mx = (w + e) / 2; my = (s + n) / 2
        out = []
        for sub in [(w, s, mx, my), (mx, s, e, my), (w, my, mx, n), (mx, my, e, n)]:
            out += pull_tiled(uipt, sub, depth + 1)
        return out
    return rows

def num(x):
    try: return float(str(x).replace(",", "").replace("$", ""))
    except Exception: return None

def main(only):
    out = {}
    for name, rkind, box in REGIONS:
        if only and not any(o.lower() in name.lower() for o in only): continue
        got = Counter()
        for uipt, kind in KINDS:
            for r in pull_tiled(uipt, box):
                url = next((v for k, v in r.items() if k and k.startswith("URL")), None)
                price = num(r.get("PRICE")); lat = num(r.get("LATITUDE")); lng = num(r.get("LONGITUDE"))
                ptype = (r.get("PROPERTY TYPE") or "").strip()
                if not (url and price and lat and lng): continue
                if kind == "land" and "land" not in ptype.lower(): continue
                if url.startswith("/"): url = "https://www.redfin.com" + url
                if url in out: continue
                lot = num(r.get("LOT SIZE"))
                out[url] = {
                    "url": url, "kind": kind, "region": name, "region_kind": rkind, "price_usd": int(price),
                    "sqft_lot": lot, "acres": round(lot / 43560, 3) if lot else None,
                    "sqft_living": num(r.get("SQUARE FEET")), "beds": num(r.get("BEDS")), "baths": num(r.get("BATHS")),
                    "year": num(r.get("YEAR BUILT")), "hoa": num(r.get("HOA/MONTH")), "lat": lat, "lng": lng,
                    "address": (r.get("ADDRESS") or "").strip(), "city": (r.get("CITY") or "").strip(),
                    "state": (r.get("STATE OR PROVINCE") or "").strip(), "dom": num(r.get("DAYS ON MARKET")),
                    "ptype": ptype,
                }
                got[kind] += 1
        print(f"  {name}: {dict(got)}", file=sys.stderr)
        json.dump(list(out.values()), open(OUT, "w"))
    print(f"TOTAL {len(out)} rows {dict(Counter(r['kind'] for r in out.values()))} -> {OUT}", file=sys.stderr)

if __name__ == "__main__":
    main(sys.argv[1:])
