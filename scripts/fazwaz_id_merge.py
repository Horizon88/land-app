"""Merge FazWaz Indonesia rows into listings.json.

Coast anchors for Bali / Lombok / Yogyakarta shorelines + highland viewpoint
bonuses (Ubud, Batur rim, Sidemen, Munduk, Rinjani foothills).

Foreign friction: Indonesia bars foreigners from freehold (Hak Milik).
Hak Pakai (30+20+20 yr, renewable) on titled land, leasehold, or PT PMA
for commercial. −20 like other lease-only jurisdictions.
"""
import json, math, statistics, sys
from collections import Counter

raw = json.load(open("/tmp/fazwaz_id.json"))
print(f"raw FazWaz ID: {len(raw)}", file=sys.stderr)

SIZE_TIERS = [(0.1,-25),(0.25,-12),(0.5,0),(1,6),(2.5,14),(5,22),(10,32),(25,44),(50,56),(100,68),(500,80),(float("inf"),92)]
def sb(ac):
    for t,b in SIZE_TIERS:
        if ac < t: return b
    return 92

# Coast anchor points: Bali perimeter, Lombok, Yogyakarta south coast
COAST = [
    # Bali (clockwise from Canggu)
    (-8.66,115.13),(-8.68,115.16),(-8.75,115.17),(-8.80,115.23),(-8.72,115.45),
    (-8.51,115.61),(-8.28,115.60),(-8.06,115.19),(-8.12,114.95),(-8.23,114.62),
    (-8.40,114.62),(-8.58,114.93),(-8.62,115.08),
    # Nusa islands
    (-8.68,115.45),(-8.73,115.54),
    # Lombok
    (-8.49,116.04),(-8.35,116.10),(-8.31,116.40),(-8.55,116.75),(-8.90,116.55),
    (-8.92,116.28),(-8.87,116.05),
    # Yogyakarta south coast
    (-7.98,110.32),(-8.01,110.61),(-7.90,110.05),
]

# Highland / caldera viewpoints
VP = [
    ("Ubud",           -8.507, 115.263),
    ("Batur rim",      -8.242, 115.375),
    ("Sidemen valley", -8.470, 115.430),
    ("Munduk",         -8.270, 115.070),
    ("Rinjani (Sembalun)", -8.350, 116.530),
    ("Borobudur",      -7.608, 110.204),
]

def hav(a,b,c,d):
    R=6371
    dl=math.radians(c-a); dlo=math.radians(d-b)
    h=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

upms = [r["price_usd"]/r["sqm"] for r in raw if r.get("price_usd") and r.get("sqm") and r["sqm"] >= 100]
med_upm = statistics.median(upms) if upms else 200

rows = []
for r in raw:
    sqm = r.get("sqm") or 0
    usd = r.get("price_usd") or 0
    if sqm < 100 or usd < 5000: continue
    ac = round(sqm / 4046.86, 3)
    upm = round(usd / sqm, 2 if usd/sqm < 10 else 1)
    lat, lng = r.get("lat") or 0, r.get("lng") or 0

    rb = ["src:fazwaz-id"]
    score = 16; rb.append("acc+16")
    b = sb(ac); score += b; rb.append(f"size{'+' if b>=0 else ''}{b}")

    ratio = upm / med_upm if med_upm else 1
    if ratio < 0.4: vb = 10
    elif ratio < 0.7: vb = 6
    elif ratio < 1.0: vb = 3
    elif ratio < 1.5: vb = 0
    elif ratio < 2.5: vb = -3
    else: vb = -6
    if vb: score += vb; rb.append(f"val{'+' if vb>0 else ''}{vb}")

    coast_km = None
    vp_hits = []
    if lat and lng:
        coast_km = round(min(hav(lat, lng, a, b) for a, b in COAST), 2)
        if coast_km <= 0.5: score += 18; rb.append("beachfront+18")
        elif coast_km <= 2: score += 12; rb.append("coast≤2km+12")
        elif coast_km <= 10: score += 6; rb.append("coast≤10km+6")
        best = min(((hav(lat, lng, vla, vlo), n) for n, vla, vlo in VP))
        if best[0] <= 3: score += 20; rb.append("vp≤3km+20"); vp_hits.append({"name": best[1], "km": round(best[0],1)})
        elif best[0] <= 10: score += 12; rb.append("vp≤10km+12"); vp_hits.append({"name": best[1], "km": round(best[0],1)})
        elif best[0] <= 25: score += 6; rb.append("vp≤25km+6"); vp_hits.append({"name": best[1], "km": round(best[0],1)})

    dist_bonus = r.get("distress_bonus") or 0
    if dist_bonus > 0:
        score += dist_bonus
        rb.append(f"forced-sale+{dist_bonus}")

    score -= 20; rb.append("foreign_id_leasehold-20")

    rows.append({
        "tp": "land", "cf": "Indonesia",
        "r": round(score, 1),
        "rg": r.get("region", "Bali"),
        "a": r.get("area_name", "")[:40],
        "ac": ac, "m2": int(sqm), "usd": usd, "upm": upm,
        "v": "sea_visible" if coast_km is not None and coast_km <= 2 else ("mountain" if vp_hits else ""),
        "el": "",
        "t": "Leasehold / Hak Pakai (verify title!)",
        "lat": lat, "lon": lng,
        "cur": "USD", "lp": str(usd),
        "rb": "+".join(rb),
        "img": "", "imgs": [r["img"]] if r.get("img") else [],
        "u": r["url"],
        "apt": "", "apt_km": None,
        "name": r.get("title", "")[:180],
        "ski_km": None, "ski_r": "",
        "coast_km": coast_km,
        "foreign_friction": -20,
        "viewpoints": vp_hits or None,
    })

existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing = [e for e in existing if "src:fazwaz-id" not in (e.get("rb", "") or "")]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda x: x.get("r", 0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json", "w"), separators=(",", ":"))
print(f"merged: {len(rows)} new Indonesia rows; total {len(merged)}", file=sys.stderr)
print("by region:", Counter(r["rg"] for r in rows).most_common(), file=sys.stderr)
