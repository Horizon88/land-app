"""Merge LandQuest (BC + Alberta mountain/rural land) into listings.json.

Ski proximity scored against the CA resorts in ski_resorts.json.
Canada: no foreign-friction penalty scored here, but note: Canada's
foreign-buyer ban (2023-2026, extended to Jan 2027) exempts VACANT LAND —
raw land is one of the few property classes foreigners can still buy.
"""
import json, math, statistics, sys
from collections import Counter
from html import unescape

raw = json.load(open("/tmp/landquest.json"))
print(f"raw LandQuest: {len(raw)}", file=sys.stderr)

CADUSD = 0.73

SKI = [(r["name"], r["lat"], r["lon"]) for r in json.load(open("/home/user/land-app/scripts/ski_resorts.json"))
       if r["region"].startswith("CA")]

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

upms = [(r["cad"]*CADUSD)/(r["acres"]*4046.86) for r in raw if r.get("cad") and r.get("acres")]
med_upm = statistics.median(upms) if upms else 5

rows = []
for r in raw:
    ac = r.get("acres")
    cad = r.get("cad") or 0
    if not ac or ac < 0.1 or cad < 20000: continue
    m2 = ac * 4046.86
    usd = round(cad * CADUSD)
    upm = round(usd / m2, 2 if usd/m2 < 10 else 1)
    lat, lng = r.get("lat"), r.get("lng")

    rb = ["src:landquest"]
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
        elif ski_km <= 30: score += 5; rb.append("ski≤30km+5")
        if ac >= 5 and ski_km <= 40: score += 8; rb.append("sled+8")

    region = unescape(r.get("region", "")).strip()
    prov = r.get("prov", "BC")

    rows.append({
        "tp": "land", "cf": "Canada",
        "r": round(score, 1),
        "rg": region[:30] if region else prov,
        "a": "",
        "ac": round(ac, 3), "m2": int(m2), "usd": usd, "upm": upm,
        "v": "mountain",
        "el": "",
        "t": "Freehold (vacant land exempt from CA foreign-buyer ban)",
        "lat": lat, "lon": lng,
        "cur": "CAD", "lp": str(cad),
        "rb": "+".join(rb),
        "img": "", "imgs": [r["img"]] if r.get("img") else [],
        "u": r["url"],
        "apt": "", "apt_km": None,
        "name": unescape(r.get("title", ""))[:180],
        "ski_km": ski_km, "ski_r": ski_r,
        "coast_km": None,
        "foreign_friction": 0,
        "alpine": True,
    })

existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing = [e for e in existing if "src:landquest" not in (e.get("rb", "") or "")]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda x: x.get("r", 0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json", "w"), separators=(",", ":"))
print(f"merged: {len(rows)} new LandQuest rows; total {len(merged)}", file=sys.stderr)
print("by region:", Counter(r["rg"] for r in rows).most_common(), file=sys.stderr)
