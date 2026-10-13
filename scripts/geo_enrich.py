"""Geo enrichment: real distance-to-sea for Japan, distance-to-lake for Austria.

Build once (needs Natural Earth geojson downloaded to a folder):
    python3 -I scripts/geo_enrich.py build <natural-earth-dir>
writes compact point sets to scripts/geo/ (committed, ~2 MB).

Annotate listings (idempotent; run after any Japan/Austria merge):
    python3 scripts/geo_enrich.py apply [file ...]   (default docs/listings.json)
sets coast_km on Japan rows; lake_km + lake on Austria rows.
"""
import json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
GEO = os.path.join(HERE, "geo")
JP_BBOX = (122.0, 24.0, 146.5, 46.0)      # lon/lat
AT_BBOX = (9.4, 46.3, 17.2, 49.1)

# Austrian lakes missing from Natural Earth: (name, axis lat/lon list, half-width km)
EXTRA_LAKES = [
    ("Zeller See",        [(47.338, 12.795), (47.290, 12.805)], 0.6),
    ("Wolfgangsee",       [(47.770, 13.355), (47.745, 13.420), (47.718, 13.478)], 0.8),
    ("Mondsee",           [(47.855, 13.355), (47.800, 13.420)], 0.8),
    ("Achensee",          [(47.505, 11.705), (47.425, 11.725)], 0.5),
    ("Millstätter See",   [(46.818, 13.510), (46.773, 13.648)], 0.7),
    ("Ossiacher See",     [(46.645, 13.890), (46.700, 14.000)], 0.6),
    ("Faaker See",        [(46.575, 13.925), (46.578, 13.940)], 0.7),
    ("Weissensee",        [(46.712, 13.300), (46.700, 13.400)], 0.4),
    ("Hallstätter See",   [(47.590, 13.650), (47.530, 13.660)], 0.6),
    ("Grundlsee",         [(47.630, 13.830), (47.615, 13.900)], 0.4),
    ("Plansee",           [(47.480, 10.800), (47.460, 10.840)], 0.4),
    ("Fuschlsee",         [(47.800, 13.270), (47.790, 13.310)], 0.4),
    ("Klopeiner See",     [(46.605, 14.578), (46.606, 14.592)], 0.4),
    ("Irrsee",            [(47.920, 13.300), (47.880, 13.320)], 0.3),
    ("Wolfgangsee (St. Gilgen)", [(47.766, 13.366), (47.760, 13.380)], 0.5),
    # tighten the big lakes whose Natural Earth outline is coarse
    ("Wörthersee",        [(46.616, 14.040), (46.635, 14.165), (46.620, 14.255)], 0.7),
    ("Attersee",          [(47.900, 13.535), (47.845, 13.545), (47.790, 13.550)], 1.2),
    ("Traunsee",          [(47.915, 13.795), (47.860, 13.790), (47.810, 13.770)], 0.9),
]

def hav(a, b, c, d):
    R = 6371; dl = math.radians(c - a); dlo = math.radians(d - b)
    h = math.sin(dl/2)**2 + math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

def densify(coords, step_km):
    """coords: [(lon,lat),...] → points every ~step_km along the line, as (lat,lon)."""
    out = []
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        d = hav(y1, x1, y2, x2); n = max(1, int(d / step_km))
        for i in range(n):
            t = i / n
            out.append((round(y1 + (y2-y1)*t, 4), round(x1 + (x2-x1)*t, 4)))
    if coords: out.append((round(coords[-1][1], 4), round(coords[-1][0], 4)))
    return out

def in_bbox(x, y, b): return b[0] <= x <= b[2] and b[1] <= y <= b[3]

def lines_of(geom):
    t = geom["type"]; c = geom["coordinates"]
    if t == "LineString": return [c]
    if t == "MultiLineString": return c
    if t == "Polygon": return c
    if t == "MultiPolygon": return [ring for poly in c for ring in poly]
    return []

def build(ne_dir):
    os.makedirs(GEO, exist_ok=True)
    coast = json.load(open(os.path.join(ne_dir, "ne_10m_coastline.geojson")))
    pts = []
    for ft in coast["features"]:
        for line in lines_of(ft["geometry"]):
            if any(in_bbox(x, y, JP_BBOX) for x, y in line):
                pts += [p for p in densify(line, 0.4) if in_bbox(p[1], p[0], JP_BBOX)]
    json.dump(pts, open(os.path.join(GEO, "japan_coast_pts.json"), "w"), separators=(",", ":"))
    lakes = []
    for f in ("ne_10m_lakes_europe.geojson", "ne_10m_lakes.geojson"):
        g = json.load(open(os.path.join(ne_dir, f)))
        for ft in g["features"]:
            if not ft["geometry"]: continue
            name = ft["properties"].get("name") or ft["properties"].get("name_en") or "lake"
            for ring in lines_of(ft["geometry"]):
                if any(in_bbox(x, y, AT_BBOX) for x, y in ring):
                    lakes.append({"name": str(name).title() if str(name).isupper() else str(name),
                                  "pts": densify(ring, 0.2), "hw": 0})
    for name, axis, hw in EXTRA_LAKES:
        lakes.append({"name": name.split(" (")[0], "pts": densify([(lo, la) for la, lo in axis], 0.2), "hw": hw})
    json.dump(lakes, open(os.path.join(GEO, "austria_lakes.json"), "w"), separators=(",", ":"), ensure_ascii=False)
    print(f"japan coast points: {len(pts)} · austria lakes: {len(lakes)}", file=sys.stderr)

class Grid:
    def __init__(self, pts, cell=0.1):
        self.cell = cell; self.g = {}
        for i, (la, lo) in enumerate(pts):
            self.g.setdefault((int(la/cell), int(lo/cell)), []).append(i)
        self.pts = pts
    def nearest(self, la, lo, rings=3):
        ci, cj = int(la/self.cell), int(lo/self.cell); best = None
        for r in range(rings + 1):
            for di in range(-r, r+1):
                for dj in range(-r, r+1):
                    if max(abs(di), abs(dj)) != r: continue
                    for i in self.g.get((ci+di, cj+dj), ()):
                        p = self.pts[i]; d = hav(la, lo, p[0], p[1])
                        if best is None or d < best[0]: best = (d, i)
            if best is not None and best[0] < r * self.cell * 80: break
        return best

def apply(files):
    coast = Grid([tuple(p) for p in json.load(open(os.path.join(GEO, "japan_coast_pts.json")))])
    lakes = json.load(open(os.path.join(GEO, "austria_lakes.json")))
    lake_pts, lake_meta = [], []
    for k, L in enumerate(lakes):
        for p in L["pts"]: lake_pts.append(tuple(p)); lake_meta.append(k)
    lake_grid = Grid(lake_pts, cell=0.05)
    for f in files:
        d = json.load(open(f)); nj = na = 0
        for r in d:
            la, lo = r.get("lat"), r.get("lon", r.get("lng"))
            if la is None or lo is None: continue
            if r.get("cf") == "Japan":
                b = coast.nearest(la, lo, rings=4)
                r["coast_km"] = round(b[0], 2) if b and b[0] < 40 else None; nj += 1
            elif r.get("cf") == "Austria":
                b = lake_grid.nearest(la, lo, rings=3)
                if b and b[0] < 15:
                    L = lakes[lake_meta[b[1]]]
                    r["lake_km"] = round(max(0.0, b[0] - L["hw"]), 2); r["lake"] = L["name"]
                else:
                    r.pop("lake_km", None); r.pop("lake", None)
                na += 1
        json.dump(d, open(f, "w"), separators=(",", ":"), ensure_ascii=False)
        print(f"{f}: coast_km on {nj} Japan rows · lake_km on {na} Austria rows", file=sys.stderr)

if __name__ == "__main__":
    if sys.argv[1] == "build": build(sys.argv[2])
    else: apply(sys.argv[2:] or [os.path.join(HERE, "..", "docs", "listings.json")])
