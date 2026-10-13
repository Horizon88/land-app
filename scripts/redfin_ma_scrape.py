"""Redfin — South Coast Massachusetts land + homes (Buzzards Bay / Mount Hope Bay).

The Land.com network (landsearch/landwatch/landandfarm) now 403s, and
realtor.com rate-limits, but Redfin's gis-csv export is open and accepts a
geographic polygon. We pull vacant land AND homes (single-family, condo,
townhouse) for the South Coast region. Redfin caps each query at 350 rows,
so the region is tiled and any tile that hits the cap is split again.

South Coast MA = the Buzzards Bay + Mount Hope Bay mainland coast: Seekonk,
Swansea, Somerset, Fall River, Westport, Dartmouth, New Bedford, Acushnet,
Fairhaven, Mattapoisett, Marion, Rochester, Wareham (west of the Cape Cod
Canal; the Cape/islands are excluded). Emits /tmp/redfin_ma.json.
"""
import csv, io, json, subprocess, sys, time, urllib.parse
from collections import Counter

RELAY = "https://landrelay.flag-theory.workers.dev"
OUT = "/tmp/redfin_ma.json"
BBOX = (-71.38, 41.45, -70.66, 41.90)     # west, south, east, north
CAP = 350
KINDS = [("5", "land"), ("1,2,3", "house")]   # 5 land · 1 SFR, 2 condo, 3 townhouse

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
           f"&uipt={uipt}&v=8&market=boston&poly={urllib.parse.quote(poly(*box))}")
    body = relay(url)
    lines = [l for l in body.splitlines() if l and not l.startswith('"In accordance')]
    if not lines or not lines[0].startswith("SALE TYPE"):
        return []
    return list(csv.DictReader(io.StringIO("\n".join(lines))))

def pull_tiled(uipt, box, depth=0):
    rows = pull(uipt, box)
    time.sleep(0.4)
    if len(rows) >= CAP - 5 and depth < 3:          # hit the cap → quarter the tile
        w, s, e, n = box; mx = (w + e) / 2; my = (s + n) / 2
        out = []
        for sub in [(w, s, mx, my), (mx, s, e, my), (w, my, mx, n), (mx, my, e, n)]:
            out += pull_tiled(uipt, sub, depth + 1)
        return out
    return rows

def num(x):
    try: return float(str(x).replace(",", "").replace("$", ""))
    except Exception: return None

def grid(box, nx, ny):
    w, s, e, n = box; dx = (e - w) / nx; dy = (n - s) / ny
    return [(w + i*dx, s + j*dy, w + (i+1)*dx, s + (j+1)*dy) for i in range(nx) for j in range(ny)]

if __name__ == "__main__":
    out = {}
    for uipt, kind in KINDS:
        tiles = [BBOX] if kind == "land" else grid(BBOX, 3, 2)
        got = 0
        for t in tiles:
            for r in pull_tiled(uipt, t):
                url = next((v for k, v in r.items() if k and k.startswith("URL")), None)
                price = num(r.get("PRICE"))
                lat = num(r.get("LATITUDE")); lng = num(r.get("LONGITUDE"))
                state = (r.get("STATE OR PROVINCE") or "").strip()
                ptype = (r.get("PROPERTY TYPE") or "").strip()
                if not (url and price and lat and lng) or state != "MA":
                    continue
                if kind == "land" and "land" not in ptype.lower():
                    continue
                if url.startswith("/"): url = "https://www.redfin.com" + url
                if url in out: continue
                lot = num(r.get("LOT SIZE"))
                out[url] = {
                    "url": url, "kind": kind, "price_usd": int(price),
                    "sqft_lot": lot, "acres": round(lot/43560, 3) if lot else None,
                    "sqft_living": num(r.get("SQUARE FEET")),
                    "beds": num(r.get("BEDS")), "baths": num(r.get("BATHS")),
                    "year": num(r.get("YEAR BUILT")), "hoa": num(r.get("HOA/MONTH")),
                    "lat": lat, "lng": lng,
                    "address": (r.get("ADDRESS") or "").strip(),
                    "city": (r.get("CITY") or "").strip(), "zip": (r.get("ZIP OR POSTAL CODE") or "").strip(),
                    "state": state, "dom": num(r.get("DAYS ON MARKET")), "ptype": ptype,
                }
                got += 1
        print(f"  {kind}: {got} rows", file=sys.stderr)
    json.dump(list(out.values()), open(OUT, "w"))
    print(f"TOTAL {len(out)} South Coast MA rows {dict(Counter(r['kind'] for r in out.values()))} -> {OUT}", file=sys.stderr)
    print("homes by city:", Counter(r["city"] for r in out.values() if r["kind"]=="house").most_common(15), file=sys.stderr)
