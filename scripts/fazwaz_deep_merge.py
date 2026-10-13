"""Merge deep-sweep FazWaz rows (append-only; URL-deduped against existing).
Scoring mirrors fazwaz_south_th_merge."""
import json, math, statistics, sys
from collections import Counter

raw = json.load(open("/tmp/fazwaz_deep.json"))
print(f"raw deep rows: {len(raw)}", file=sys.stderr)

SIZE_TIERS = [(0.1,-25),(0.25,-12),(0.5,0),(1,6),(2.5,14),(5,22),(10,32),(25,44),(50,56),(100,68),(500,80),(float("inf"),92)]
def sb(ac):
    for t,b in SIZE_TIERS:
        if ac < t: return b
    return 92

COAST_TH_S = [
    (10.00,98.75),(9.50,98.36),(8.20,98.30),(7.90,98.30),
    (7.63,98.60),(7.30,99.10),(7.00,99.35),(6.65,99.65),(6.55,100.10),
    (7.20,100.60),(8.43,99.96),(9.50,100.00),(9.72,100.02),(9.75,100.03),
    (10.50,99.18),(11.50,99.20),(12.50,99.90),
]
def hav(a,b,c,d):
    R=6371
    dl=math.radians(c-a); dlo=math.radians(d-b)
    h=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

upms = [r["price_usd"]/r["sqm"] for r in raw if r.get("price_usd") and r.get("sqm") and r["sqm"] >= 100]
med_upm = statistics.median(upms) if upms else 400

rows = []
for r in raw:
    sqm = r.get("sqm") or 0
    usd = r.get("price_usd") or 0
    if sqm < 200 or usd < 5000: continue
    ac = round(sqm / 4046.86, 3)
    raw_upm = usd / sqm
    upm = round(raw_upm, 3 if raw_upm < 1 else (2 if raw_upm < 10 else 1))
    lat, lng = r.get("lat") or 0, r.get("lng") or 0

    rb = ["src:fazwaz-deep"]
    score = 16; rb.append("acc+16")
    b = sb(ac); score += b; rb.append(f"size{'+' if b>=0 else ''}{b}")
    ratio = upm / med_upm if med_upm else 1
    vb = 10 if ratio<0.4 else 6 if ratio<0.7 else 3 if ratio<1.0 else 0 if ratio<1.5 else -3 if ratio<2.5 else -6
    if vb: score += vb; rb.append(f"val{'+' if vb>0 else ''}{vb}")
    coast_km = None
    if lat and lng:
        coast_km = round(min(hav(lat,lng,a,b) for a,b in COAST_TH_S), 2)
        if coast_km <= 0.5: score += 18; rb.append("beachfront+18")
        elif coast_km <= 2: score += 12; rb.append("coast≤2km+12")
        elif coast_km <= 10: score += 6; rb.append("coast≤10km+6")
    db = r.get("distress_bonus") or 0
    if db: score += db; rb.append(f"forced-sale+{db}")
    score -= 25; rb.append("foreign_th_land-25")

    rows.append({
        "tp": "land", "cf": "Thailand", "r": round(score,1),
        "rg": r["province"], "a": "",
        "ac": ac, "m2": int(sqm), "usd": usd, "upm": upm,
        "v": "sea_visible" if coast_km is not None and coast_km <= 2 else "",
        "el": "", "t": "Chanote (verify)", "lat": lat, "lon": lng,
        "cur": "USD", "lp": str(usd), "rb": "+".join(rb),
        "imgs": [r["img"]] if r.get("img") else [],
        "u": r["url"], "apt": "", "apt_km": None,
        "name": (r.get("title") or "")[:180],
        "ski_km": None, "ski_r": "", "coast_km": coast_km,
        "foreign_friction": -25,
    })

existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda x: x.get("r",0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json", "w"), separators=(",", ":"))
print(f"merged: {len(rows)} new deep rows; total {len(merged)}", file=sys.stderr)
print("by province:", Counter(r["rg"] for r in rows).most_common(), file=sys.stderr)
