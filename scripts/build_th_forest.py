"""Convert Overpass Thai protected-area response to a compact GeoJSON layer.

Each Overpass relation → 1 GeoJSON Feature (Polygon or MultiPolygon).
Coordinates rounded to 4 decimals (≈11m resolution — fine for "encroaches?"
flags). Douglas-Peucker simplification tolerance 0.001° drops ~85% of points.

Skips Laos ones (Overpass area query bleeds a little across the Mekong).
"""
import json, sys

def simplify(pts, tol=0.001):
    """Douglas-Peucker on [(lat,lng), ...] returning simplified list."""
    if len(pts) < 3: return pts[:]
    # perpendicular distance from p to line (a,b)
    def pd(p, a, b):
        (px,py),(ax,ay),(bx,by) = p, a, b
        dx, dy = bx-ax, by-ay
        if dx==0 and dy==0: return ((px-ax)**2+(py-ay)**2)**0.5
        t = ((px-ax)*dx + (py-ay)*dy) / (dx*dx+dy*dy)
        t = max(0, min(1, t))
        nx, ny = ax + t*dx, ay + t*dy
        return ((px-nx)**2+(py-ny)**2)**0.5
    dmax, imax = 0, 0
    for i in range(1, len(pts)-1):
        d = pd(pts[i], pts[0], pts[-1])
        if d > dmax: dmax, imax = d, i
    if dmax > tol:
        left = simplify(pts[:imax+1], tol)
        right = simplify(pts[imax:], tol)
        return left[:-1] + right
    return [pts[0], pts[-1]]

def build_ring(members_with_role):
    """Chain matching endpoints of member ways to form one closed ring."""
    ways = [[(pt["lat"], pt["lon"]) for pt in m["geometry"]] for m in members_with_role if m.get("geometry")]
    if not ways: return None
    ring = list(ways.pop(0))
    while ways:
        last = ring[-1]
        matched = False
        for i, w in enumerate(ways):
            if w[0] == last: ring.extend(w[1:]); ways.pop(i); matched=True; break
            if w[-1] == last: ring.extend(reversed(w[:-1])); ways.pop(i); matched=True; break
            if w[0] == ring[0]: ring = list(reversed(w[1:])) + ring; ways.pop(i); matched=True; break
            if w[-1] == ring[0]: ring = w[:-1] + ring; ways.pop(i); matched=True; break
        if not matched: break  # broken relation — take what we have
    return ring

d = json.load(open("/tmp/th_pa_geom.json"))
features = []
skipped = 0
for e in d["elements"]:
    tags = e.get("tags", {}) or {}
    name = tags.get("name", "")
    name_en = tags.get("name:en", "")
    # Skip Lao entries (some cross-border relations included)
    if any(k in name for k in ["ປ່າ", "ນະຄອນ"]) and not name_en:
        skipped += 1; continue
    # Get outer members
    outers = [m for m in e.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
    inners = [m for m in e.get("members", []) if m.get("role") == "inner" and m.get("geometry")]
    if not outers: skipped += 1; continue
    outer_ring = build_ring(outers)
    if not outer_ring or len(outer_ring) < 4:
        skipped += 1; continue
    # Simplify + swap to lng,lat (GeoJSON convention)
    outer_simp = simplify(outer_ring, tol=0.001)
    if len(outer_simp) < 4: skipped += 1; continue
    outer_geo = [[round(lo, 4), round(la, 4)] for la, lo in outer_simp]
    # Ensure closed
    if outer_geo[0] != outer_geo[-1]:
        outer_geo.append(outer_geo[0])
    rings = [outer_geo]
    # Handle inner rings (holes)
    if inners:
        inner_ring = build_ring(inners)
        if inner_ring and len(inner_ring) >= 4:
            inner_simp = simplify(inner_ring, tol=0.001)
            if len(inner_simp) >= 4:
                inner_geo = [[round(lo, 4), round(la, 4)] for la, lo in inner_simp]
                if inner_geo[0] != inner_geo[-1]: inner_geo.append(inner_geo[0])
                rings.append(inner_geo)
    boundary = tags.get("boundary") or tags.get("leisure") or "protected"
    protect_class = tags.get("protect_class", "")
    features.append({
        "type": "Feature",
        "properties": {
            "id": e["id"],
            "name": name,
            "name_en": name_en,
            "boundary": boundary,
            "protect_class": protect_class,
        },
        "geometry": {"type": "Polygon", "coordinates": rings},
    })

fc = {"type": "FeatureCollection", "features": features}
out = "/home/user/land-app/docs/th_forests.geojson"
json.dump(fc, open(out, "w"), separators=(",", ":"))

import os
sz = os.path.getsize(out)
print(f"features: {len(features)} (skipped {skipped})", file=sys.stderr)
print(f"file size: {sz/1024:.1f} KB", file=sys.stderr)
