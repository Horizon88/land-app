"""Merge thailand-property.com land into listings.json.

Dedups by geo+price against existing inventory (it syndicates FazWaz and
overlaps DotProperty). Scores like the other Thai sources; distress from
description keywords only (no reliable datePosted on these detail pages).
"""
import json, math, re, statistics, sys
from collections import Counter

RAW = "/tmp/thailandproperty.json"
PATH = "/home/user/land-app/docs/listings.json"
raw = json.load(open(RAW))
print(f"raw thailand-property: {len(raw)}", file=sys.stderr)

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
    R=6371; dl=math.radians(c-a); dlo=math.radians(d-b)
    h=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

DISTRESS_PATS = [
    (r'urgent|ด่วน','urgent',15),(r'must sell|quick sale','must-sell',18),
    (r'reduced|price drop|ลดราคา','price-drop',15),(r'below market','below-market',15),
    (r'motivated','motivated',18),(r'leaving|relocat|ย้าย','leaving',12),
    (r'divorce','divorce',15),(r'negotiab|ต่อรอง','negotiable',8),
]

existing = json.load(open(PATH))
th_exist = [(e["lat"], e["lon"], e.get("usd") or 0) for e in existing
            if e.get("cf") == "Thailand" and e.get("lat") and e.get("usd")]
def is_dup(lat, lng, usd):
    for la, lo, u in th_exist:
        if abs(la-lat) < 0.002 and abs(lo-lng) < 0.002 and hav(la,lo,lat,lng) < 0.08:
            if u and usd and abs(u-usd)/max(u,usd) < 0.1:
                return True
    return False

upms = [r["price_thb"]/36/r["sqm"] for r in raw if r.get("price_thb") and r.get("sqm") and r["sqm"]>=100]
med_upm = statistics.median(upms) if upms else 400

rows = []; dup = 0
for r in raw:
    sqm = r.get("sqm"); thb = r.get("price_thb")
    if not sqm or sqm < 100 or not thb: continue
    usd = round(thb/36)
    if usd < 5000: continue
    lat = r.get("lat"); lng = r.get("lng")
    if lat and lng and is_dup(lat, lng, usd): dup += 1; continue
    ac = round(sqm/4046.86, 3)
    raw_upm = usd/sqm
    upm = round(raw_upm, 3 if raw_upm<1 else (2 if raw_upm<10 else 1))

    rb = ["src:thailand-property"]
    score = 16; rb.append("acc+16")
    b = sb(ac); score += b; rb.append(f"size{'+' if b>=0 else ''}{b}")
    ratio = upm/med_upm if med_upm else 1
    vb = 10 if ratio<0.4 else 6 if ratio<0.7 else 3 if ratio<1.0 else 0 if ratio<1.5 else -3 if ratio<2.5 else -6
    if vb: score += vb; rb.append(f"val{'+' if vb>0 else ''}{vb}")

    coast_km = None
    if lat and lng:
        coast_km = round(min(hav(lat,lng,a,b) for a,b in COAST_TH_S), 2)
        if coast_km <= 0.5: score += 18; rb.append("beachfront+18")
        elif coast_km <= 2: score += 12; rb.append("coast≤2km+12")
        elif coast_km <= 10: score += 6; rb.append("coast≤10km+6")

    text = (r.get("name") or "").lower()
    dist = 0; dbrk = []
    for pat, tag, w in DISTRESS_PATS:
        if re.search(pat, text): dist += w; dbrk.append([tag, w])
    dist = min(dist, 100)
    if dist: score += min(dist, 40); rb.append(f"distress+{min(dist,40)}")

    deed = ""
    if re.search(r'chanote|โฉนด', text): deed = "Chanote"
    elif re.search(r'nor ?sor ?3|น\.?ส\.?3', text): deed = "NS3"

    score -= 25; rb.append("foreign_th_land-25")

    rows.append({
        "tp":"land","cf":"Thailand","r":round(score,1),
        "rg": r.get("province","Thailand"), "a": (r.get("locality") or "")[:40],
        "ac":ac, "m2":int(sqm), "usd":usd, "upm":upm,
        "v":"sea_visible" if coast_km is not None and coast_km<=2 else "",
        "el":"", "t": deed or "verify title", "lat":lat, "lon":lng,
        "cur":"THB", "lp":str(thb), "rb":"+".join(rb),
        "imgs":[], "u":r["url"], "name": (r.get("name") or "")[:180],
        "ski_km":None, "ski_r":"", "coast_km":coast_km,
        "distress": dist or None, "distress_breakdown": dbrk or None,
        "foreign_friction": -25,
    })

# replace this source cleanly, dedup by URL against everything else
existing = [e for e in existing if "src:thailand-property" not in (e.get("rb","") or "")]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda x: x.get("r",0), reverse=True)
json.dump(merged, open(PATH,"w"), separators=(",",":"))
print(f"merged: {len(rows)} new thailand-property rows ({dup} dropped as dupes); total {len(merged)}", file=sys.stderr)
print("by province:", Counter(r["rg"] for r in rows).most_common(), file=sys.stderr)
