"""Merge OLX Romania land into listings.json.

Foreign friction (RO): EU citizens can buy land freely; non-EU foreigners
need company-structure or reciprocity treaty. Score as -10 (medium friction
— easier than Thailand/Turkey, harder than USA/UK).
"""
import json, math, sys, statistics
from collections import Counter

raw = json.load(open("/tmp/olx_ro.json"))
print(f"raw OLX-RO rows: {len(raw)}", file=sys.stderr)
# Sanity filter — need price + (area OR will-skip-tiny)
raw = [r for r in raw if r.get("price") and r["price"] >= 1000]
print(f"after price filter: {len(raw)}", file=sys.stderr)

EUR_USD = 1.08  # rough
RON_USD = 1/4.6

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

# Compute median $/m² for value scoring
upms = [r["price"]*EUR_USD/r["sqm"] for r in raw if r.get("sqm") and r["sqm"] >= 100]
med_upm = statistics.median(upms) if upms else 50

rows = []
for r in raw:
    sqm = r.get("sqm") or 0
    if not sqm:
        continue   # need area to score
    if sqm < 200:
        continue   # require ≥ 200 m²
    ac = round(sqm / 4046.86, 3)
    if r["cur"] == "EUR":
        usd = round(r["price"] * EUR_USD)
    else:
        usd = round(r["price"] * RON_USD)
    upm = round(usd / sqm, 1)
    upa = usd / ac if ac else 0

    rb = ["src:olx-ro"]
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

    # Ski
    lat = r.get("lat") or 0; lng = r.get("lng") or 0
    ski_km, ski_r = None, None
    if lat and lng:
        best = min((hav(lat, lng, s["lat"], s["lon"]), s["name"]) for s in SKI)
        ski_km = round(best[0], 2); ski_r = best[1]
        if ski_km <= 0.5: score += 15; rb.append("ski-in+15")
        elif ski_km <= 2: score += 10; rb.append("ski≤2km+10")
        elif ski_km <= 10: score += 5; rb.append("ski≤10km+5")
        if ac >= 10 and 0.5 < ski_km <= 20: score += 8; rb.append("rope-tow+8")
        if ac >= 5 and ski_km <= 30: score += 8; rb.append("sled+8")

    # Foreign friction (RO is EU)
    score -= 10; rb.append("foreign_ro_non-eu-10")

    rows.append({
        "tp":"land","cf":"Romania","r":round(score,1),
        "rg": r.get("judet_label") or r.get("judet") or "Romania",
        "a": (r.get("loc","") or "").split(" - ")[0][:30],
        "ac":ac,"m2":int(sqm),"usd":usd,"upm":upm,
        "v":"","el":"",
        "t":"Freehold (RO: EU-citizen, or company structure)",
        "lat":lat,"lon":lng,
        "cur": r["cur"], "lp": str(r["price"]),
        "rb":"+".join(rb),
        "img": r.get("img","") or "", "imgs": [r["img"]] if r.get("img") else [],
        "u": r["url"] or f"https://www.olx.ro/d/oferta/-ID{r['id']}.html",
        "apt":"","apt_km":None,
        "name": r.get("title","")[:140],
        "ski_km": ski_km, "ski_r": ski_r,
        "foreign_friction": -10,
        "foreign_note": "EU citizens: freehold OK. Non-EU: needs RO company structure (unless reciprocity treaty).",
    })

# Merge
existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing = [e for e in existing if e.get("cf") != "Romania" and "src:olx-ro" not in (e.get("rb","") or "")]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda r: r.get("r",0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json","w"))
print(f"merged: {len(rows)} new RO rows; total {len(merged)}", file=sys.stderr)

top = sorted(rows, key=lambda r: r.get("r",0), reverse=True)[:10]
print("\nTOP 10 RO:", file=sys.stderr)
for r in top:
    print(f"  ★{r['r']:>5}  {r['ac']:>6}ac  ${r['usd']:>9,}  ski={r['ski_km']}km {(r['ski_r'] or '')[:18]:<18}  {r['rg']:<12}  {r['name'][:50]}", file=sys.stderr)
