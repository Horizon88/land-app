"""Merge OLX Poland land into listings.json.

Foreign friction (PL): EU citizens unrestricted. Non-EU: agricultural >1ha
requires Ministry permit; non-agri land < 30m from sea or border restricted.
Score -10 for non-EU friction (similar to Romania).
"""
import json, math, sys, statistics
from collections import Counter

raw = json.load(open("/tmp/olx_pl.json"))
print(f"raw OLX-PL rows: {len(raw)}", file=sys.stderr)
raw = [r for r in raw if r.get("price") and r["price"] >= 1000]
print(f"after price filter: {len(raw)}", file=sys.stderr)

PLN_USD = 1/3.95
EUR_USD = 1.08

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

upms = []
for r in raw:
    if r.get("sqm") and r["sqm"] >= 100 and r["price"]:
        usd = r["price"] * (PLN_USD if r["cur"]=="PLN" else EUR_USD)
        upms.append(usd / r["sqm"])
med_upm = statistics.median(upms) if upms else 30

rows = []
for r in raw:
    sqm = r.get("sqm") or 0
    if not sqm: continue
    if sqm < 200: continue
    ac = round(sqm / 4046.86, 3)
    usd = round(r["price"] * (PLN_USD if r["cur"]=="PLN" else EUR_USD))
    upm = round(usd / sqm, 1)

    rb = ["src:olx-pl"]
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
    if lat and lng:
        best = min((hav(lat, lng, s["lat"], s["lon"]), s["name"]) for s in SKI)
        ski_km = round(best[0], 2); ski_r = best[1]
        if ski_km <= 0.5: score += 15; rb.append("ski-in+15")
        elif ski_km <= 2: score += 10; rb.append("ski≤2km+10")
        elif ski_km <= 10: score += 5; rb.append("ski≤10km+5")
        if ac >= 10 and 0.5 < ski_km <= 20: score += 8; rb.append("rope-tow+8")
        if ac >= 5 and ski_km <= 30: score += 8; rb.append("sled+8")

    score -= 10; rb.append("foreign_pl_non-eu-10")

    rows.append({
        "tp":"land","cf":"Poland","r":round(score,1),
        "rg": r.get("woj_label") or "Poland",
        "a": (r.get("loc","") or "").split(",")[0][:30],
        "ac":ac,"m2":int(sqm),"usd":usd,"upm":upm,
        "v":"","el":"",
        "t":"Freehold (PL: EU-citizen, non-EU needs permit for ag-land >1ha)",
        "lat":lat,"lon":lng,
        "cur": r["cur"], "lp": str(r["price"]),
        "rb":"+".join(rb),
        "img": r.get("img","") or "", "imgs": [r["img"]] if r.get("img") else [],
        "u": r["url"] or f"https://www.olx.pl/d/oferta/-ID{r['id']}.html",
        "apt":"","apt_km":None,
        "name": r.get("title","")[:140],
        "ski_km": ski_km, "ski_r": ski_r,
        "foreign_friction": -10,
        "foreign_note": "EU: freehold. Non-EU: needs Ministry permit for ag-land >1ha; border/coastal land restricted.",
    })

existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing = [e for e in existing if e.get("cf") != "Poland" and "src:olx-pl" not in (e.get("rb","") or "")]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda r: r.get("r",0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json","w"))
print(f"merged: {len(rows)} new PL rows; total {len(merged)}", file=sys.stderr)

top = sorted(rows, key=lambda r: r.get("r",0), reverse=True)[:10]
print("\nTOP 10 PL:", file=sys.stderr)
for r in top:
    print(f"  ★{r['r']:>5}  {r['ac']:>6}ac  ${r['usd']:>9,}  ski={r['ski_km']}km {(r['ski_r'] or '')[:18]:<18}  {r['rg']:<14}  {r['name'][:50]}", file=sys.stderr)
