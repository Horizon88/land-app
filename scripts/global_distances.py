"""Recompute coast_km and ski_km for every listing from global data.

Earlier scrapers set coast_km from regional coastlines (some countries ended up
with nonsense, e.g. US mountain land "3,270 km" from the sea) and ski_km from
hand-made resort lists. This replaces both, for all countries:

  coast_km  distance to the ocean coastline (Natural Earth 10m), None beyond 50 km
  ski_km    distance to the nearest operating ski lift (OpenSkiMap / OpenStreetMap)
            at a ski area with 3+ real lifts (chairs, gondolas, T-bars, platters...),
            None beyond 30 km; ski_r = that ski area's name, ski_lifts = its lift count

Usage: python3 scripts/global_distances.py [files...]   (defaults to listings + saved plots)
Downloads are cached in $GEO_CACHE (default /tmp/geo_cache).
"""
import json, math, os, sys, urllib.request
from collections import Counter, defaultdict
import numpy as np
from scipy.spatial import cKDTree

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CACHE = os.environ.get("GEO_CACHE", "/tmp/geo_cache")
COAST_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_coastline.geojson"
LIFTS_URL = "https://tiles.openskimap.org/geojson/lifts.geojson"
SKI_LIFTS = {"chair_lift", "gondola", "t-bar", "platter", "drag_lift", "j-bar", "mixed_lift", "cable_car"}
R = 6371.0

def fetch(url, name):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name)
    if not os.path.exists(p):
        print("downloading", url, file=sys.stderr)
        urllib.request.urlretrieve(url, p)
    return p

def xyz(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])

def chord_to_km(c):
    return 2 * R * np.arcsin(np.clip(c / 2, 0, 1))

def densify(coords, step_km, keep=None):
    """[(lon,lat),...] -> (lat,lon) points every ~step_km; segments outside keep(lat,lon) are skipped."""
    out = []
    coords = [c[:2] for c in coords]          # some sources carry elevation as a 3rd value
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        if keep and not (keep(y1, x1) or keep(y2, x2)): continue
        d = math.hypot((y2 - y1) * 111, (x2 - x1) * 111 * math.cos(math.radians(y1)))
        n = max(1, int(d / step_km))
        for i in range(n + 1):
            t = i / n
            out.append((y1 + (y2 - y1) * t, x1 + (x2 - x1) * t))
    return out

def main(files):
    rows_by_file = {f: json.load(open(f)) for f in files}
    pts = [(r["lat"], r.get("lon", r.get("lng"))) for d in rows_by_file.values() for r in d
           if r.get("lat") is not None and r.get("lon", r.get("lng")) is not None]
    cells = {(int(math.floor(a)) + di, int(math.floor(b)) + dj) for a, b in pts for di in (-1, 0, 1) for dj in (-1, 0, 1)}
    near = lambda la, lo: (int(math.floor(la)), int(math.floor(lo))) in cells

    # ---- coastline: densify only near listings
    coast = json.load(open(fetch(COAST_URL, "ne_10m_coastline.geojson")))
    cpts = []
    for ft in coast["features"]:
        g = ft["geometry"]
        lines = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        for ln in lines: cpts += densify(ln, 0.2, near)
    ca = np.array(cpts)
    ctree = cKDTree(xyz(ca[:, 0], ca[:, 1]))
    print(f"coast points near listings: {len(ca):,}", file=sys.stderr)

    # ---- ski lifts at real ski areas
    lifts = json.load(open(fetch(LIFTS_URL, "lifts.geojson")))["features"]
    area_n = Counter(); keep = []
    for ft in lifts:
        p = ft["properties"]
        if p.get("status") != "operating" or p.get("liftType") not in SKI_LIFTS or not p.get("skiAreas"): continue
        a = p["skiAreas"][0]["properties"]
        if "downhill" not in (a.get("activities") or []): continue
        area_n[a["id"]] += 1
        keep.append((a["id"], a.get("name") or "ski area", ft["geometry"]))
    spts, sidx, names = [], [], {}
    for aid, name, g in keep:
        if area_n[aid] < 3: continue
        names[aid] = name
        lines = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"] if g["type"] == "MultiLineString" else []
        for ln in lines:
            for la, lo in densify(ln, 0.1, near):
                spts.append((la, lo)); sidx.append(aid)
    sa = np.array(spts)
    stree = cKDTree(xyz(sa[:, 0], sa[:, 1]))
    print(f"ski lift points near listings: {len(sa):,} from {len(names):,} ski areas", file=sys.stderr)

    for f, d in rows_by_file.items():
        idx = [i for i, r in enumerate(d) if r.get("lat") is not None and r.get("lon", r.get("lng")) is not None]
        if not idx: continue
        P = xyz(np.array([d[i]["lat"] for i in idx]), np.array([d[i].get("lon", d[i].get("lng")) for i in idx]))
        cd, _ = ctree.query(P); sd, si = stree.query(P)
        ckm, skm = chord_to_km(cd), chord_to_km(sd)
        before = Counter(); after = Counter()
        for k, i in enumerate(idx):
            r = d[i]
            if (r.get("coast_km") or 99) <= 1: before[r.get("cf")] += 1
            r["coast_km"] = round(float(ckm[k]), 2) if ckm[k] <= 50 else None
            if skm[k] <= 30:
                aid = sidx[si[k]]
                r["ski_km"] = round(float(skm[k]), 2); r["ski_r"] = names[aid]; r["ski_lifts"] = area_n[aid]
            else:
                r["ski_km"] = None; r["ski_r"] = ""; r.pop("ski_lifts", None)
            if r["coast_km"] is not None and r["coast_km"] <= 1: after[r.get("cf")] += 1
        json.dump(d, open(f, "w"), separators=(",", ":"), ensure_ascii=False) if f.endswith("listings.json") \
            else json.dump(d, open(f, "w"), ensure_ascii=False, indent=4)
        ski2 = Counter(d[i].get("cf") for i in idx if (d[i].get("ski_km") or 99) <= 2)
        print(f"{os.path.basename(f)}: {len(idx)} rows · within 1 km of the sea, before→after: "
              + ", ".join(f"{c} {before[c]}→{after[c]}" for c in sorted(set(before) | set(after), key=lambda c: -after[c])[:12])
              + f" · within 2 km of a lift: {dict(ski2.most_common(10))}", file=sys.stderr)

if __name__ == "__main__":
    main(sys.argv[1:] or [os.path.join(ROOT, "docs", "listings.json"), os.path.join(ROOT, "docs", "saved_plots.json")])
