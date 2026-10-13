"""Merge SUUMO mountain-Japan rows into listings.json.

Scoring mirrors the coastal-Japan style: access base, size tiers, value vs
regional median, ski proximity against the 65 JP resorts in ski_resorts.json.
Japan has no foreign-ownership friction (freehold OK for foreigners).
"""
import json, math, sys
from collections import Counter

raw = json.load(open("/tmp/suumo_mountain.json"))
print(f"raw suumo mountain rows: {len(raw)}", file=sys.stderr)

SKI = [(r["name"], r["lat"], r["lon"]) for r in json.load(open("/home/user/land-app/scripts/ski_resorts.json"))
       if r["region"].startswith("JP")]

SIZE_TIERS = [(0.1,-25),(0.25,-12),(0.5,0),(1,6),(2.5,14),(5,22),(10,32),(25,44),(50,56),(100,68),(500,80),(float("inf"),92)]
def sb(ac):
    for t,b in SIZE_TIERS:
        if ac < t: return b
    return 92

def hav(a,b,c,d):
    R=6371
    dl=math.radians(c-a); dlo=math.radians(d-b)
    h=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

import statistics
upms = [r["usd"]/r["m2"] for r in raw if r.get("usd") and r.get("m2")]
med_upm = statistics.median(upms) if upms else 30

rows = []
for r in raw:
    m2 = r.get("m2") or 0
    usd = r.get("usd") or 0
    if m2 < 150 or usd < 3000: continue
    ac = round(m2 / 4046.86, 3)
    upm = round(usd / m2, 2 if usd/m2 < 10 else 1)
    lat, lng = r["lat"], r["lng"]

    rb = ["src:suumo-mtn"]
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

    ski_km, ski_r = None, ""
    if lat and lng:
        ski_km, ski_r = min(((hav(lat, lng, la, lo), n) for n, la, lo in SKI))
        ski_km = round(ski_km, 2)
        if ski_km <= 2: score += 15; rb.append("ski≤2km+15")
        elif ski_km <= 10: score += 10; rb.append("ski≤10km+10")
        elif ski_km <= 25: score += 5; rb.append("ski≤25km+5")

    # geocode precision note: city centroid, not parcel
    gsrc = r.get("geocode_src", "pref")

    rows.append({
        "tp": "land", "cf": "Japan",
        "r": round(score, 1),
        "rg": r["pref"],
        "a": r["city"].replace("_", " ").title()[:40],
        "ac": ac, "m2": int(m2) if m2 >= 100 else m2, "usd": usd, "upm": upm,
        "v": "mountain",
        "el": "",
        "t": "Freehold (Japan; foreigners OK)",
        "lat": lat, "lon": lng,
        "cur": "JPY", "lp": str(r["price_jpy"]),
        "rb": "+".join(rb),
        "img": "", "imgs": [],
        "u": r["url"],
        "apt": "", "apt_km": None,
        "name": f"{round(m2):,} m² — {r['city'].replace('_',' ').title()}, {r['pref']}",
        "ski_km": ski_km, "ski_r": ski_r,
        "coast_km": None,
        "foreign_friction": 0,
        "geocode_src": gsrc,
        "alpine": True,
    })

existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing = [e for e in existing if "src:suumo-mtn" not in (e.get("rb", "") or "")]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda x: x.get("r", 0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json", "w"), separators=(",", ":"))
print(f"merged: {len(rows)} new suumo-mtn rows; total {len(merged)}", file=sys.stderr)
print("by pref:", Counter(r["rg"] for r in rows).most_common(), file=sys.stderr)
