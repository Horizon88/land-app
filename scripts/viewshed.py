"""Viewshed: can you actually SEE the water (and how much of it) from a listing?

Distance-to-water isn't a view: 300 m from the sea behind a hill sees
nothing; a hillside 2 km up can see the whole bay. For each candidate listing
this casts 72 sight lines (every 5°) over open terrain-elevation tiles (AWS
Terrain Tiles, terrarium encoding, zoom 11 ≈ 55-75 m/px) and asks, per line,
whether water is visible over the terrain within 7 km from an observer 8 m
above ground (a 2-storey window). Water = sea (elevation ≤ 0) or, in Austria,
a lake surface (flat at the lake's own level).

Bare-earth terrain only: trees and buildings are not modelled, so this says
"the land allows a view", which the listing text, photos and Claude's review
then confirm or contradict.

Writes onto each row:
  view_deg     degrees of horizon with water in sight (0-360)
  view_near_km distance to the nearest visible water
  elev_m       ground elevation
  prom_m       elevation above the median of the surrounding 1.5 km
  view_score   0-100 combining the above + listing text + photo reviews
Usage: python3 scripts/viewshed.py [docs/listings.json] [docs/saved_plots.json]
"""
import io, json, math, os, re, subprocess, sys, threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CACHE = os.environ.get("DEM_CACHE", "/tmp/dem_cache")
Z = 11
RAYS = 72
MAX_KM = 7.0
EYE_M = 8.0
os.makedirs(CACHE, exist_ok=True)

def tile_xy(lat, lon, z=Z):
    n = 2 ** z
    la = math.radians(lat)
    return ((lon + 180) / 360 * n, (1 - math.log(math.tan(la) + 1 / math.cos(la)) / math.pi) / 2 * n)

def tile_path(x, y): return os.path.join(CACHE, f"{Z}_{x}_{y}.png")

def download(xy):
    x, y = xy; p = tile_path(x, y)
    if os.path.exists(p) and os.path.getsize(p) > 100: return
    subprocess.run(["curl", "-s", "-m", "40", "-o", p,
                    f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{Z}/{x}/{y}.png"])

_lru = OrderedDict(); _lock = threading.Lock()
def tile(x, y):
    k = (x, y)
    with _lock:
        if k in _lru: _lru.move_to_end(k); return _lru[k]
    p = tile_path(x, y)
    if not os.path.exists(p): download(k)
    try:
        a = np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)
        e = a[:, :, 0] * 256 + a[:, :, 1] + a[:, :, 2] / 256 - 32768
    except Exception:
        e = None
    with _lock:
        _lru[k] = e
        if len(_lru) > 400: _lru.popitem(last=False)
    return e

def elev(fx, fy):
    x, y = int(fx), int(fy)
    t = tile(x, y)
    if t is None: return None
    px = min(255, max(0, int((fx - x) * 256))); py = min(255, max(0, int((fy - y) * 256)))
    return float(t[py, px])

# ---- Austrian lakes: flat surfaces at their own level ----
LAKES = []
def load_lakes():
    p = os.path.join(ROOT, "scripts", "geo", "austria_lakes.json")
    if not os.path.exists(p): return
    for L in json.load(open(p)):
        LAKES.append({"name": L["name"], "pts": L["pts"], "hw": L.get("hw", 0)})

_masks = {}
def lake_level(L):
    """Water level = median ground elevation along the lake's own points."""
    if L.get("level") is None:
        vals = []
        for la, lo in L["pts"][:: max(1, len(L["pts"]) // 30)]:
            fx, fy = tile_xy(la, lo); v = elev(fx, fy)
            if v is not None: vals.append(v)
        L["level"] = float(np.median(vals)) if vals else np.nan
    return L["level"]

def lake_mask(x, y):
    """Boolean 256×256 mask of lake pixels for tile (x, y), from the lake outlines
    (polygons) and hand-drawn axes (polyline ± half-width). Cached per tile."""
    if (x, y) in _masks: return _masks[(x, y)]
    n = 2 ** Z
    px = (np.arange(256) + 0.5) / 256
    lon = (x + px) / n * 360 - 180                                   # per column
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + px) / n))))  # per row
    LON, LAT = np.meshgrid(lon, lat)
    lo0, lo1, la0, la1 = lon.min(), lon.max(), lat.min(), lat.max()
    mask = np.full((256, 256), np.nan, dtype=np.float32)
    for L in LAKES:
        P = np.array(L["pts"])                      # (lat, lon)
        if P[:, 1].max() < lo0 - .05 or P[:, 1].min() > lo1 + .05 or P[:, 0].max() < la0 - .05 or P[:, 0].min() > la1 + .05:
            continue
        if L["hw"] > 0:                              # axis: within half-width of the polyline
            kx = 111320 * np.cos(np.radians(LAT)); ky = 110540
            best = np.full(LAT.shape, 1e12)
            for (a0, b0), (a1, b1) in zip(P[:-1], P[1:]):
                ax, ay = (b0 - LON) * kx, (a0 - LAT) * ky
                bx, by = (b1 - LON) * kx, (a1 - LAT) * ky
                vx, vy = bx - ax, by - ay
                t = np.clip(-(ax * vx + ay * vy) / max(vx.max() ** 2 + vy.max() ** 2, 1e-9), 0, 1) if False else                     np.clip(-(ax * vx + ay * vy) / np.maximum(vx * vx + vy * vy, 1e-9), 0, 1)
                dx_, dy_ = ax + t * vx, ay + t * vy
                best = np.minimum(best, dx_ * dx_ + dy_ * dy_)
            mask[best <= (L["hw"] * 1000) ** 2] = lake_level(L)
        else:                                        # polygon: even-odd ray casting
            inside = np.zeros(LAT.shape, dtype=bool)
            ys, xs = P[:, 0], P[:, 1]
            for i in range(len(P) - 1):
                y0, x0, y1, x1 = ys[i], xs[i], ys[i + 1], xs[i + 1]
                if y0 == y1: continue
                cond = (LAT >= min(y0, y1)) & (LAT < max(y0, y1))
                xint = x0 + (LAT - y0) * (x1 - x0) / (y1 - y0)
                inside ^= cond & (LON < xint)
            mask[inside] = lake_level(L)
    _masks[(x, y)] = mask
    return mask

def viewshed(lat, lon, cf):
    fx0, fy0 = tile_xy(lat, lon)
    e0 = elev(fx0, fy0)
    if e0 is None: return None
    ground = max(e0, 0.0)
    eye = ground + EYE_M
    # metres per pixel at this latitude
    mpp = 40075016.686 * math.cos(math.radians(lat)) / (2 ** Z) / 256
    step = mpp; nsteps = int(MAX_KM * 1000 / step)
    use_lakes = cf == "Austria" and bool(LAKES)
    vis_rays = 0; near = None; ring = []
    for k in range(RAYS):
        az = 2 * math.pi * k / RAYS
        dx, dy = math.sin(az), -math.cos(az)
        best = -1e9; seen = False
        for s in range(1, nsteps + 1):
            d = s * step
            fx = fx0 + dx * s / 256; fy = fy0 + dy * s / 256
            e = elev(fx, fy)
            if e is None: break
            if 1300 <= d <= 1600: ring.append(e)
            curv = d * d / (2 * 6371000) * 0.87
            ang = (e - curv - eye) / d
            water = e <= 0.5
            if not water and use_lakes:
                tx, ty = int(fx), int(fy)
                lv = lake_mask(tx, ty)[min(255, int((fy - ty) * 256)), min(255, int((fx - tx) * 256))]
                water = bool(lv == lv and abs(e - lv) < 2.0)      # inside the outline AND at the water's level
            if water and ang >= best - 1e-4 and not seen:
                seen = True
                if near is None or d < near * 1000: near = d / 1000
            if ang > best: best = ang
            if seen and d > 1500: break
        vis_rays += seen
    prom = ground - float(np.median(ring)) if ring else 0.0
    return {"view_deg": round(vis_rays * 360 / RAYS), "view_near_km": round(near, 2) if near is not None else None,
            "elev_m": round(ground), "prom_m": round(prom)}

VIEW_WORDS = re.compile(r"sea view|ocean view|water view|views? of the|panoram|vista|seaview|oceanfront|waterfront|"
                        r"seeblick|bergblick|fernblick|海一望|海が見え|眺望|絶景|オーシャン|vue mer|vista al mar|vista mar|"
                        r"widok|tầm nhìn|วิวทะเล|sea-view|lake view|mountain view", re.I)

def score(r, v, review):
    s = 0.0; why = []
    wet = bool(v and v.get("elev_m") is not None and v["elev_m"] <= 0.5)   # pin lands in the water: arc/prominence unreliable
    if wet: v = dict(v, prom_m=0)
    if v:
        deg = v["view_deg"]
        s += min(45, deg / 180 * 45)
        nk = v["view_near_km"]
        if nk is not None:
            s += 15 if nk <= 0.3 else 12 if nk <= 1 else 8 if nk <= 3 else 4
        p = v["prom_m"] or 0
        s += 10 if p >= 60 else 7 if p >= 30 else 4 if p >= 12 else 0
    txt = " ".join([r.get("name") or "", " ".join(r.get("perks") or [])])
    if any(re.search(r"sea view|lake view|Fuji|great view|panorama|waterfront", p) for p in (r.get("perks") or [])):
        s += 15
    elif VIEW_WORDS.search(txt):
        s += 10
    if r.get("v") in ("beachfront", "waterfront", "sea_view"): s += 6
    if review:
        s += 15 if review.get("thumb") == "up" else -30 if review.get("thumb") == "down" else 0
    if wet: s = min(s, 75)
    if r.get("loc_approx"): s = min(s, 55)          # can't trust a town-centre pin for a view claim
    return max(0, min(100, round(s)))

def main(files):
    load_lakes()
    reviews = {}
    rp = os.path.join(ROOT, "docs", "reviews.json")
    if os.path.exists(rp): reviews = json.load(open(rp)).get("reviews", {})
    for f in files:
        d = json.load(open(f))
        def cand(r):
            if r.get("tp") in ("apartment", "abandoned_ski", "penthouse") or r.get("lat") is None: return False
            c = r.get("coast_km")
            return (c is not None and c <= 8) or r.get("cf") == "Austria" or \
                   (r.get("ski_km") is not None and r["ski_km"] <= 10) or r.get("user_added")
        rows = [r for r in d if cand(r)]
        if RESCORE:    # recompute view_score from stored viewshed fields (after score() tweaks / new reviews)
            for r in rows:
                v = {k: r.get(k) for k in ("view_deg", "view_near_km", "elev_m", "prom_m")} if r.get("view_deg") is not None else None
                if v and v["elev_m"] is not None and v["elev_m"] <= 0.5: r["prom_m"] = None
                r["view_score"] = score(r, v, reviews.get(r.get("u")))
            json.dump(d, open(f, "w"), separators=(",", ":"), ensure_ascii=False) if f.endswith("listings.json") \
                else json.dump(d, open(f, "w"), ensure_ascii=False, indent=4)
            print(f"{f}: rescored {len(rows)}", file=sys.stderr); continue
        # pre-download every tile the sight lines can touch (parallel), then work tile-by-tile
        need = set()
        for r in rows:
            fx, fy = tile_xy(r["lat"], r["lon"])
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1): need.add((int(fx) + dx, int(fy) + dy))
        need = [t for t in need if not os.path.exists(tile_path(*t))]
        print(f"{f}: {len(rows)} candidates · downloading {len(need)} terrain tiles", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=12) as ex:
            for i, _ in enumerate(ex.map(download, need), 1):
                if i % 500 == 0: print(f"  tiles {i}/{len(need)}", file=sys.stderr)
        rows.sort(key=lambda r: tuple(int(c) for c in tile_xy(r["lat"], r["lon"])))
        done = 0
        for r in rows:
            v = viewshed(r["lat"], r["lon"], r.get("cf"))
            if v: r.update(v)
            r["view_score"] = score(r, v, reviews.get(r.get("u")))
            done += 1
            if done % 1000 == 0: print(f"  viewshed {done}/{len(rows)}", file=sys.stderr)
        json.dump(d, open(f, "w"), separators=(",", ":"), ensure_ascii=False) if f.endswith("listings.json") \
            else json.dump(d, open(f, "w"), ensure_ascii=False, indent=4)
        top = sorted(rows, key=lambda r: -r.get("view_score", 0))[:8]
        print(f"{f}: view_score set on {len(rows)} rows; top:", file=sys.stderr)
        for r in top:
            print(f"   {r.get('view_score'):3} {r.get('code','')} {r.get('cf')}/{r.get('rg')} "
                  f"{r.get('view_deg')}° water · near {r.get('view_near_km')} km · +{r.get('prom_m')} m", file=sys.stderr)

RESCORE = "--rescore" in sys.argv
if __name__ == "__main__":
    sys.argv = [a for a in sys.argv if a != "--rescore"]
    main(sys.argv[1:] or [os.path.join(ROOT, "docs", "saved_plots.json"), os.path.join(ROOT, "docs", "listings.json")])
