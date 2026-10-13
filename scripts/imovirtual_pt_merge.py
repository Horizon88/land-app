"""Merge Portugal imovirtual into listings.json.

Foreign friction (PT): EU citizens unrestricted. Non-EU: full freehold OK
too, no Golden Visa required (though Golden Visa now excludes residential
real estate as of 2024). Score 0 (unusually foreigner-friendly).
"""
import json, math, sys, statistics
from collections import Counter

raw = json.load(open("/tmp/imovirtual_pt.json"))
print(f"raw PT rows: {len(raw)}", file=sys.stderr)

SIZE_TIERS = [(0.1,-25),(0.25,-12),(0.5,0),(1,6),(2.5,14),(5,22),(10,32),(25,44),(50,56),(100,68),(500,80),(float("inf"),92)]
def size_bonus(ac):
    for t,b in SIZE_TIERS:
        if ac < t: return b
    return 92

SKI = json.load(open("/tmp/ski_resorts.json"))
def hav(a, b, c, d):
    R = 6371
    dl = math.radians(c-a); dlo = math.radians(d-b)
    h = math.sin(dl/2)**2 + math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

# Portugal coastline anchor points (Atlantic + Algarve)
COAST_PT = [
    (41.70,-8.85),(41.15,-8.68),(40.65,-8.75),(39.75,-9.10),  # NW coast
    (38.75,-9.50),(38.55,-9.20),(38.10,-8.85),(37.85,-8.80),  # Lisbon → Sines
    (37.10,-8.80),(37.05,-8.30),(37.10,-7.70),(37.00,-7.40),  # Algarve
    (32.75,-16.95),(38.72,-27.22),  # Madeira, Azores
]

# Compute median $/m² for value
upms = [r["price_usd"]/r["sqm"] for r in raw if r.get("sqm") and r["sqm"] >= 100 and r.get("price_usd")]
med_upm = statistics.median(upms) if upms else 50

rows = []
for r in raw:
    sqm = r.get("sqm") or 0
    if not sqm or sqm < 200: continue
    if sqm > 100_000_000: continue  # >10,000ha impossible
    usd = r.get("price_usd") or 0
    if usd < 3000: continue
    ac = round(sqm / 4046.86, 3)
    upm = round(usd / sqm, 1)

    rb = ["src:imovirtual-pt"]
    score = 16; rb.append("acc+16")
    sb = size_bonus(ac); score += sb; rb.append(f"size{'+' if sb>=0 else ''}{sb}")
    if med_upm and upm:
        ratio = upm / med_upm
        if ratio < 0.4: vb = 10
        elif ratio < 0.7: vb = 6
        elif ratio < 1.0: vb = 3
        elif ratio < 1.5: vb = 0
        elif ratio < 2.5: vb = -3
        else: vb = -6
        if vb: score += vb; rb.append(f"val{'+' if vb>0 else ''}{vb}")

    lat = r.get("lat") or 0; lng = r.get("lng") or 0
    ski_km, ski_r = None, None
    coast_km = None
    if lat and lng:
        best = min((hav(lat, lng, s["lat"], s["lon"]), s["name"]) for s in SKI)
        ski_km = round(best[0], 2); ski_r = best[1]
        if ski_km <= 0.5: score += 15; rb.append("ski-in+15")
        elif ski_km <= 2: score += 10; rb.append("ski≤2km+10")
        elif ski_km <= 10: score += 5; rb.append("ski≤10km+5")
        if ac >= 10 and 0.5 < ski_km <= 20: score += 8; rb.append("rope-tow+8")
        if ac >= 5 and ski_km <= 30: score += 8; rb.append("sled+8")
        coast_km = round(min(hav(lat, lng, a, b) for a,b in COAST_PT), 2)
        if coast_km <= 0.5: score += 18; rb.append("beachfront+18")
        elif coast_km <= 2: score += 12; rb.append("coast≤2km+12")
        elif coast_km <= 10: score += 6; rb.append("coast≤10km+6")

    # PT: no foreign friction (score 0)
    rb.append("foreign_pt_ok+0")

    rows.append({
        "tp":"land","cf":"Portugal","r":round(score,1),
        "rg": (r.get("province") or r.get("district","Portugal")).replace("-"," "),
        "a": (r.get("city") or "")[:30],
        "ac":ac,"m2":int(sqm),"usd":usd,"upm":upm,
        "v":"","el":"",
        "t":"Freehold (PT: no foreign-ownership restriction)",
        "lat":lat,"lon":lng,
        "cur":"EUR","lp":str(r.get("price_eur",0)),
        "rb":"+".join(rb),
        "img": r.get("img","") or "",
        "imgs": [r["img"]] if r.get("img") else [],
        "u": r["url"],
        "apt":"","apt_km":None,
        "name": r.get("title","")[:140],
        "ski_km": ski_km, "ski_r": ski_r,
        "coast_km": coast_km,
        "foreign_friction": 0,
        "foreign_note": "Portugal: freehold for anyone; Golden Visa no longer covers residential real estate (post-2024).",
    })

existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing = [e for e in existing if e.get("cf") != "Portugal" and "src:imovirtual-pt" not in (e.get("rb","") or "")]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda r: r.get("r",0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json","w"))
print(f"merged: {len(rows)} new PT rows; total {len(merged)}", file=sys.stderr)

top = sorted(rows, key=lambda r: r.get("r",0), reverse=True)[:10]
print("\nTOP 10 PT:", file=sys.stderr)
for r in top:
    print(f"  ★{r['r']:>5}  {r['ac']:>6}ac  ${r['usd']:>10,}  ski={r['ski_km']}km coast={r['coast_km']}km  {r['rg']:<18}  {r['name'][:50]}", file=sys.stderr)
