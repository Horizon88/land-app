"""Merge USA LandWatch scrape into listings.json. Apply ski + size bonuses."""
import json, math, statistics, sys

raw = json.load(open("/tmp/usa_landsearch.json"))
print(f"raw USA rows: {len(raw)}", file=sys.stderr)

# Drop rows without sane price + acres
raw = [r for r in raw if r.get("price_usd") and r.get("acres") and r["acres"] >= 0.1]
print(f"after sanity filter: {len(raw)}", file=sys.stderr)

# Compact + score
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

upas = sorted(r["price_usd"]/r["acres"] for r in raw if r["acres"] > 0.1)
med_upa = statistics.median(upas) if upas else 5000

rows = []
for r in raw:
    ac = round(r["acres"], 2)
    m2 = round(ac * 4046.86, 1)
    usd = int(r["price_usd"])
    upm = round(usd/m2, 1) if m2 else 0
    upa = usd/ac if ac else 0
    rb = ["src:landsearch"]
    score = 0
    score += 16; rb.append("acc+16")
    sb = size_bonus(ac)
    score += sb; rb.append(f"size{'+' if sb>=0 else ''}{sb}")
    # Value
    if med_upa and upa:
        ratio = upa/med_upa
        if ratio < 0.4: vb = 10
        elif ratio < 0.7: vb = 6
        elif ratio < 1.0: vb = 3
        elif ratio < 1.5: vb = 0
        elif ratio < 2.5: vb = -3
        else: vb = -6
        if vb: rb.append(f"val{'+' if vb>0 else ''}{vb}"); score += vb
    # Ski
    best = min((hav(r["lat"], r["lon"], s["lat"], s["lon"]), s["name"]) for s in SKI)
    ski_km = round(best[0], 2)
    ski_r = best[1]
    if ski_km <= 0.5: score += 15; rb.append("ski-in+15")
    elif ski_km <= 2: score += 10; rb.append("ski≤2km+10")
    elif ski_km <= 10: score += 5; rb.append("ski≤10km+5")
    if ac >= 10 and 0.5 < ski_km <= 20: score += 8; rb.append("rope-tow+8")
    if ac >= 5 and ski_km <= 30: score += 8; rb.append("sled+8")
    # Coast proximity (matters for MA/coastal regions)
    # Approximate coast: nearest of several coastal anchor points (Cape Cod,
    # Westport MA, RI south coast, Block Island, Long Island, NJ Shore).
    COAST_ANCHORS = [
        (41.6688, -69.9650),  # Chatham, Cape Cod
        (42.0500, -70.1900),  # Provincetown
        (41.6362, -70.9342),  # Westport MA south coast
        (41.4854, -71.3128),  # Westerly RI
        (41.3145, -72.0928),  # Block Island
        (41.7000, -70.7000),  # Plymouth Bay
        (41.3805, -70.6456),  # Edgartown, MV
        (41.2835, -70.0995),  # Nantucket
    ]
    coast_km = min(hav(r["lat"], r["lon"], a, b) for a,b in COAST_ANCHORS)
    coast_km = round(coast_km, 2)
    if coast_km <= 0.5: score += 18; rb.append("beachfront+18")
    elif coast_km <= 2: score += 12; rb.append("coast≤2km+12")
    elif coast_km <= 10: score += 6; rb.append("coast≤10km+6")
    # USA no foreign-friction penalty
    rows.append({
        "tp":"land","cf":"USA","r":round(score,1),
        "rg": r["region"], "a":"",
        "ac":ac,"m2":m2,"usd":usd,"upm":upm,
        "v":"","el":"","t":"Freehold",
        "lat":r["lat"],"lon":r["lon"],
        "cur":"USD","lp":str(usd),
        "rb":"+".join(rb),
        "img":"","imgs":[],
        "u":r["url"],
        "apt":"","apt_km":None,
        "name":r.get("title",""),
        "ski_km":ski_km,"ski_r":ski_r,"coast_km":coast_km,
        "foreign_friction":0,
        "foreign_note":"no foreign-ownership restriction federally",
    })

# Merge: strip prior cf=USA rows (idempotent)
existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing = [e for e in existing if e.get("cf") != "USA"]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda r: r.get("r",0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json","w"))
print(f"merged: {len(rows)} new USA rows; total {len(merged)}", file=sys.stderr)

# Top USA
us = sorted(rows, key=lambda r: r.get("r",0), reverse=True)[:12]
print("\nTOP 12 USA by rating:", file=sys.stderr)
for r in us:
    print(f"  ★{r['r']:>5} {r['ac']:>6}ac  ${r['usd']:>9,}  ski={r['ski_km']}km {r['ski_r'][:18]:<18}  {r['rg']}", file=sys.stderr)
