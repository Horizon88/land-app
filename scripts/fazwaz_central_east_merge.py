"""Merge FazWaz Southern Thailand into listings.json with distress detection."""
import json, math, sys, statistics
from collections import Counter

raw = json.load(open("/tmp/fazwaz_central_east.json"))
print(f"raw FazWaz SoTH: {len(raw)}", file=sys.stderr)

SIZE_TIERS = [(0.1,-25),(0.25,-12),(0.5,0),(1,6),(2.5,14),(5,22),(10,32),(25,44),(50,56),(100,68),(500,80),(float("inf"),92)]
def sb(ac):
    for t,b in SIZE_TIERS:
        if ac < t: return b
    return 92

# Coast anchor set for Central/Eastern Thailand (Gulf coast)
COAST_TH_S = [
    # Central Gulf (Bangkok → Pattaya → Rayong → Trat)
    (13.60,100.60),(13.55,100.27),(13.42,100.00),(13.11,99.94),(12.80,99.97),
    (12.57,99.96),(11.81,99.79),(11.00,99.30),(10.50,99.20),
    # Eastern Gulf
    (13.36,100.98),(12.92,100.88),(12.66,100.90),(12.68,101.28),
    (12.61,102.10),(12.24,102.51),(12.05,102.35),(11.65,102.55),
]
def hav(a,b,c,d):
    R=6371
    dl=math.radians(c-a); dlo=math.radians(d-b)
    h=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

# Iconic viewpoints (also used by viewpoint_bonus.py)
VP = [
    ("Samet Nangshe",  8.3628, 98.5122),
    ("Ao Nang",        8.0333, 98.8250),
    ("Railay",         8.0114, 98.8402),
]

# Compute median $/m² for value
upms = [r["price_usd"]/r["sqm"] for r in raw if r.get("price_usd") and r.get("sqm") and r["sqm"] >= 100]
med_upm = statistics.median(upms) if upms else 400

rows = []
for r in raw:
    sqm = r.get("sqm") or 0
    if not sqm or sqm < 200: continue
    usd = r.get("price_usd") or 0
    if usd < 5000: continue
    ac = round(sqm / 4046.86, 3)
    upm = round(usd / sqm, 1)

    rb = ["src:fazwaz-cent-east"]
    score = 16; rb.append("acc+16")
    b = sb(ac); score += b; rb.append(f"size{'+' if b>=0 else ''}{b}")

    if med_upm and upm:
        ratio = upm / med_upm
        if ratio < 0.4: vb = 10
        elif ratio < 0.7: vb = 6
        elif ratio < 1.0: vb = 3
        elif ratio < 1.5: vb = 0
        elif ratio < 2.5: vb = -3
        else: vb = -6
        if vb: score += vb; rb.append(f"val{'+' if vb>0 else ''}{vb}")

    lat = r.get("lat") or 0
    lng = r.get("lng") or 0
    coast_km = None
    vp_hits = []
    if lat and lng:
        coast_km = round(min(hav(lat, lng, a, b) for a,b in COAST_TH_S), 2)
        if coast_km <= 0.5: score += 18; rb.append("beachfront+18")
        elif coast_km <= 2: score += 12; rb.append("coast≤2km+12")
        elif coast_km <= 10: score += 6; rb.append("coast≤10km+6")
        # Viewpoints
        for name, vlat, vlng in VP:
            d = hav(lat, lng, vlat, vlng)
            if d <= 3: score += 25; rb.append(f"vp≤3km+25"); vp_hits.append({"name":name,"km":round(d,1)})
            elif d <= 10: score += 18; rb.append(f"vp≤10km+18"); vp_hits.append({"name":name,"km":round(d,1)})
            elif d <= 25: score += 10; rb.append(f"vp≤25km+10"); vp_hits.append({"name":name,"km":round(d,1)})
            elif d <= 40: score += 5; rb.append(f"vp≤40km+5"); vp_hits.append({"name":name,"km":round(d,1)})

    # Distress from keyword scan
    dist_bonus = r.get("distress_bonus") or 0
    if dist_bonus > 0:
        score += dist_bonus
        # tag as forced-sale so weight bucket picks it up
        rb.append(f"forced-sale+{dist_bonus}")

    # Thai foreign-friction
    score -= 25; rb.append("foreign_th_land-25")

    rows.append({
        "tp": "land", "cf": "Thailand",
        "r": round(score, 1),
        "rg": r["province"],
        "a": "",
        "ac": ac, "m2": int(sqm), "usd": usd, "upm": upm,
        "v": "sea_visible" if coast_km and coast_km <= 2 else "",
        "el": "",
        "t": "Chanote (Thai)",
        "lat": lat, "lon": lng,
        "cur": "USD", "lp": str(usd),
        "rb": "+".join(rb),
        "img": r.get("img") or "",
        "imgs": [r["img"]] if r.get("img") else [],
        "u": r["url"],
        "apt": "", "apt_km": None,
        "name": (r.get("title","") or "")[:160],
        "ski_km": None, "coast_km": coast_km,
        "viewpoints": vp_hits or None,
        "distress": min(100, dist_bonus + 5) if dist_bonus else None,
        "distress_breakdown": [(h, int(h.split("+")[-1])) for h in r.get("distress_hits",[])] if dist_bonus else None,
        "distress_keywords": r.get("distress_hits") or None,
        "foreign_friction": -25,
        "foreign_note": "Foreigners can't own Thai land — need Thai company or long-term lease.",
    })

# Merge — strip prior fazwaz-southth rows
existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing = [e for e in existing if "src:fazwaz-cent-east" not in (e.get("rb","") or "")]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda r: r.get("r",0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json","w"))
print(f"merged: {len(rows)} new FazWaz-SoTH rows; total {len(merged)}", file=sys.stderr)

by_prov = Counter(r["rg"] for r in rows)
n_dist = sum(1 for r in rows if r.get("distress"))
print(f"by province: {by_prov.most_common()}", file=sys.stderr)
print(f"distressed: {n_dist}", file=sys.stderr)

if n_dist:
    print("\nTop DISTRESSED:", file=sys.stderr)
    dist = [r for r in rows if r.get("distress")]
    dist.sort(key=lambda r: r.get("r",0), reverse=True)
    for r in dist[:8]:
        kws = ", ".join(r.get("distress_keywords") or [])
        print(f"  ★{r['r']:>5}  {r['ac']:>6}ac  ${r['usd']:>9,}  {r['rg']:<15}  [{kws[:60]}]", file=sys.stderr)
