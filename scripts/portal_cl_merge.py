"""Merge Chile Portalinmobiliario into listings.json.

Foreign friction (CL): no restrictions on foreign ownership federally,
but border zones (10km from Argentine/Peruvian border) require presidential
authorization for foreigners. Coastal DL-1939 zone (Bienes Nacionales)
sometimes needs decree. Score -5 as light friction (Andes/coastal near
national borders may hit border-zone rules).
"""
import json, math, sys, statistics
from collections import Counter

UF_USD = 40.0    # UF ≈ $40 in mid-2026 (inflation-indexed, floats)
CLP_USD = 1/930  # CLP peso ≈ $0.00107

raw = json.load(open("/tmp/portal_cl.json"))
print(f"raw CL rows: {len(raw)}", file=sys.stderr)

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

# Region → English
REGION_EN = {
    "Santiago-Andes":"Central Andes","Valparaiso":"Valparaíso",
    "Nuble":"Ñuble","Araucania":"Araucanía","Los-Lagos":"Los Lagos",
    "Los-Rios":"Los Ríos","Aysen":"Aysén","Magallanes":"Magallanes",
    "Valparaiso-coast":"Valparaíso Coast",
}

# Compute median $/m² for value scoring
upms = []
for r in raw:
    sqm = r.get("sqm") or 0
    if sqm and 100 < sqm < 5000000:
        usd = (r["price"] * UF_USD) if r["cur"] == "UF" else (r["price"] * CLP_USD)
        upms.append(usd / sqm)
med_upm = statistics.median(upms) if upms else 100

rows = []
for r in raw:
    sqm = r.get("sqm") or 0
    if not sqm or sqm < 200:
        continue
    if sqm > 100000000:  # 10,000 ha — parse error
        continue
    ac = round(sqm / 4046.86, 3)
    cur = r.get("cur","").strip()
    if cur == "UF":
        usd = round(r["price"] * UF_USD)
    elif cur in ("$","CLP"):
        usd = round(r["price"] * CLP_USD)
    else:
        continue
    if usd < 5000: continue
    upm = round(usd / sqm, 1)

    rb = ["src:portal-cl"]
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
        # Chile coastal anchors (Pacific)
        # Rough coastline sample points N to S
        COAST_CL = [(-18.5,-70.3),(-23.0,-70.5),(-27.5,-70.9),(-33.0,-71.6),
                    (-36.8,-73.1),(-40.0,-73.9),(-42.5,-73.7),(-46.0,-74.2),(-53.1,-70.9)]
        coast_km = round(min(hav(lat, lng, a, b) for a,b in COAST_CL), 2)
        if coast_km <= 0.5: score += 18; rb.append("beachfront+18")
        elif coast_km <= 2: score += 12; rb.append("coast≤2km+12")
        elif coast_km <= 10: score += 6; rb.append("coast≤10km+6")

    # Chile: border zone -5 friction
    score -= 5; rb.append("foreign_cl_border-5")

    rows.append({
        "tp":"land","cf":"Chile","r":round(score,1),
        "rg": REGION_EN.get(r.get("region",""), r.get("region","Chile")),
        "a": (r.get("loc","") or "")[:30],
        "ac":ac,"m2":int(sqm),"usd":usd,"upm":upm,
        "v":"","el":"",
        "t":"Freehold (CL: no federal restriction; border zone 10km needs decree)",
        "lat":lat,"lon":lng,
        "cur": cur, "lp": str(r["price"]),
        "rb":"+".join(rb),
        "img":"","imgs":[],
        "u": r["url"],
        "apt":"","apt_km":None,
        "name": r.get("title","")[:140],
        "ski_km": ski_km, "ski_r": ski_r,
        "coast_km": coast_km,
        "foreign_friction": -5,
        "foreign_note": "Chile: freehold OK. Border zone (10km from AR/PE/BO border) needs presidential decree for foreigners.",
    })

existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing = [e for e in existing if e.get("cf") != "Chile" and "src:portal-cl" not in (e.get("rb","") or "")]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda r: r.get("r",0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json","w"))
print(f"merged: {len(rows)} new CL rows; total {len(merged)}", file=sys.stderr)

top = sorted(rows, key=lambda r: r.get("r",0), reverse=True)[:10]
print("\nTOP 10 CL:", file=sys.stderr)
for r in top:
    print(f"  ★{r['r']:>5}  {r['ac']:>6}ac  ${r['usd']:>10,}  ski={r['ski_km']}km  {r['rg']:<18}  {r['name'][:50]}", file=sys.stderr)
