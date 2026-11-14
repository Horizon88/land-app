"""Cat-ski Alaska: which big Alaska parcels hold a skiable mountain?

For every Alaska listing of 20+ acres, samples the terrain-elevation tiles the
viewshed uses (AWS Terrain Tiles, z11) across a circle the size of the parcel
and within 3 km of it, and writes onto the row:
  cat_vert      vertical drop inside the parcel (m): highest minus lowest point
  cat_vert3     vertical from the pin up to the highest point within 3 km
                (terrain you might reach over neighbouring public land)
  cat_ski       share of the parcel at skiable pitch (20-40 degrees)
  cat_snow      the nearest heavy-snow belt and its distance (maritime ranges)
  cat_score     0-100 for the hunt: vertical, skiable pitch, snow belt, access
Pins marked approximate get their numbers but a lower score.

Usage: python3 scripts/catski_ak.py [docs/listings.json] [docs/saved_plots.json]
"""
import json, math, os, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import viewshed as vs

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
# heavy-snow maritime belts (name, lat, lon): where Alaska's deep, stable snowpack and heli/cat operations are
SNOW = [("Thompson Pass / Valdez", 61.13, -145.75), ("Valdez", 61.13, -146.35), ("Turnagain Pass", 60.80, -149.18),
        ("Girdwood / Alyeska", 60.96, -149.10), ("Hatcher Pass", 61.77, -149.29), ("Haines / Chilkat", 59.24, -135.44),
        ("Juneau / Eaglecrest", 58.27, -134.53), ("Cordova", 60.55, -145.75), ("Seward / Kenai Mountains", 60.10, -149.40),
        ("Kachemak Bay south shore", 59.50, -151.30), ("Talkeetna Mountains", 61.95, -148.60), ("Skagway / White Pass", 59.55, -135.25),
        ("Chugach front / Eagle River", 61.25, -149.30), ("Petersburg / Wrangell ranges", 56.70, -132.80), ("Ketchikan ranges", 55.40, -131.60),
        ("Kodiak", 57.80, -152.50), ("Denali / Alaska Range south", 62.95, -149.70)]

def km(a, b, c, d):
    return math.hypot((b - d) * 111.32 * math.cos(math.radians((a + c) / 2)), (a - c) * 110.57)

def sample(lat, lon, radius_m, step_m):
    pts = []
    n = int(radius_m // step_m)
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            dx, dy = i * step_m, j * step_m
            if dx * dx + dy * dy > radius_m * radius_m: continue
            la = lat + dy / 110570; lo = lon + dx / (111320 * math.cos(math.radians(lat)))
            fx, fy = vs.tile_xy(la, lo)
            try: e = vs.elev(fx, fy)
            except Exception: e = None
            if e is not None: pts.append((i, j, e))
    return pts

def analyse(r):
    ac = r.get("ac") or 0
    radius = min(2500, max(250, math.sqrt(ac * 4046.86 / math.pi)))
    step = max(40, radius / 12)
    own = sample(r["lat"], r["lon"], radius, step)
    if len(own) < 5: return None
    es = [e for _, _, e in own]
    grid = {(i, j): e for i, j, e in own}
    steep = total = 0
    for (i, j), e in grid.items():
        nb = [grid.get((i + 1, j)), grid.get((i, j + 1))]
        if None in nb: continue
        g = math.hypot(nb[0] - e, nb[1] - e) / step
        total += 1
        if 0.36 <= g <= 0.84: steep += 1          # 20-40 degrees
    far = sample(r["lat"], r["lon"], 3000, 150)
    pin = vs.elev(*vs.tile_xy(r["lat"], r["lon"]))
    vert, vert3 = max(es) - min(es), (max(e for _, _, e in far) - pin) if far and pin is not None else 0
    belt, dist = min(((n, km(r["lat"], r["lon"], a, b)) for n, a, b in SNOW), key=lambda x: x[1])
    ski = steep / total if total else 0
    score = min(45, vert / 12) + min(20, ski * 50) + (20 if dist <= 25 else 12 if dist <= 60 else 4 if dist <= 120 else 0) \
            + min(10, max(0, vert3 - vert) / 80) + (5 if r.get("imgs") else 0) - (15 if r.get("loc_approx") else 0)
    return {"cat_vert": round(vert), "cat_vert3": round(max(0, vert3)), "cat_ski": round(ski, 2),
            "cat_snow": f"{belt} · {dist:.0f} km", "cat_score": round(max(0, min(100, score)))}

def main(files):
    for f in files:
        d = json.load(open(f))
        rows = [r for r in d if r.get("state") == "AK" and r.get("lat") is not None and (r.get("ac") or 0) >= 20]
        need = set()
        for r in rows:
            fx, fy = vs.tile_xy(r["lat"], r["lon"])
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1): need.add((int(fx) + dx, int(fy) + dy))
        need = [t for t in need if not os.path.exists(vs.tile_path(*t))]
        print(f"{f}: {len(rows)} Alaska parcels of 20+ acres · downloading {len(need)} terrain tiles", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=12) as ex: list(ex.map(vs.download, need))
        for r in rows:
            a = analyse(r)
            if a: r.update(a)
        json.dump(d, open(f, "w"), separators=(",", ":"), ensure_ascii=False) if f.endswith("listings.json") \
            else json.dump(d, open(f, "w"), ensure_ascii=False, indent=4)
        top = sorted((r for r in rows if r.get("cat_score")), key=lambda r: -r["cat_score"])[:15]
        for r in top:
            print(f"  {r['cat_score']:3} {r.get('code', '')} {r.get('ac')} ac ${r.get('usd') or 0:,} vert {r['cat_vert']} m "
                  f"(+{r['cat_vert3']} m within 3 km) ski {r['cat_ski']:.0%} · {r['cat_snow']} · {r['u'][:70]}", file=sys.stderr)

if __name__ == "__main__":
    main(sys.argv[1:] or [os.path.join(ROOT, "docs", "listings.json"), os.path.join(ROOT, "docs", "saved_plots.json")])
