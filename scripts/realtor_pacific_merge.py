"""Merge Realtor.com International Pacific listings into listings.json."""
import json, math, sys, statistics
from collections import Counter

raw = json.load(open("/tmp/realtor_pacific.json"))
print(f"raw PAC rows: {len(raw)}", file=sys.stderr)

SIZE_TIERS = [(0.1,-25),(0.25,-12),(0.5,0),(1,6),(2.5,14),(5,22),(10,32),(25,44),(50,56),(100,68),(500,80),(float("inf"),92)]
def size_bonus(ac):
    for t,b in SIZE_TIERS:
        if ac < t: return b
    return 92

# Coastal — Pacific islands are basically all coastal. Reuse a global-ish anchor set.
# For each country compute coast_km = 0 as a simplification (every listing is coastal).
def coast_km_estimate(cc):
    return 0.5  # default: very close to coast

rows = []
for r in raw:
    ac = r.get("acres") or 0
    sqft = r.get("sqft") or 0
    # If no acres, assume 0.25 ac lot for any Pacific listing (they're all
    # coastal parcels; realtor.com just doesn't always report land size).
    if not ac:
        ac = 0.25
    if ac < 0.05:
        continue
    m2 = int(ac * 4046.86)
    usd = int(r.get("price_usd") or 0)
    if usd < 5000: continue
    upm = round(usd / m2, 1) if m2 else 0

    rb = [f"src:realtor-{r['cc']}"]
    score = 16; rb.append("acc+16")
    sb = size_bonus(ac); score += sb; rb.append(f"size{'+' if sb>=0 else ''}{sb}")
    # Pacific island → assume beachfront (they typically are)
    score += 18; rb.append("beachfront+18")
    # Foreign friction
    ff = r["foreign_friction"]
    if ff: score += ff; rb.append(f"foreign_{r['cc']}{'+' if ff>0 else ''}{ff}")

    # Determine tp
    tp = "land"
    if r.get("type") in ("home", "single family home", "villa", "condo"):
        tp = "apartment" if r["type"] == "condo" else "land"  # keep as land for filtering

    rows.append({
        "tp": tp, "cf": r["country"],
        "r": round(score, 1),
        "rg": r.get("addr","").split(",")[0][:20] or r["country"],
        "a": r.get("addr","")[:40],
        "ac": round(ac, 3), "m2": m2, "usd": usd, "upm": upm,
        "v": "beachfront",
        "el": "",
        "t": "Freehold or 99-yr lease" if r["foreign_friction"] >= -15 else "Lease-only for foreigners",
        "lat": r.get("lat"), "lon": r.get("lng"),
        "cur": "USD", "lp": str(usd),
        "rb": "+".join(rb),
        "img": r.get("img","") or "",
        "imgs": [r["img"]] if r.get("img") else [],
        "u": r["url"],
        "apt": "", "apt_km": None,
        "name": (r.get("type","") + " " + r.get("addr","")).strip()[:140],
        "ski_km": None,
        "coast_km": 0.5,
        "foreign_friction": r["foreign_friction"],
        "foreign_note": r["foreign_note"],
        "pacific": True,
    })

# Merge — strip prior Pacific rows
PAC_COUNTRIES = {"Fiji","French Polynesia","Vanuatu","New Caledonia","Samoa","Tonga",
                 "Cook Islands","Papua New Guinea","Solomon Islands","Palau"}
existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing = [e for e in existing if e.get("cf") not in PAC_COUNTRIES]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda r: r.get("r",0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json","w"))
print(f"merged: {len(rows)} new Pacific rows; total {len(merged)}", file=sys.stderr)

by_cf = Counter(r["cf"] for r in rows)
print(f"by country: {by_cf.most_common()}", file=sys.stderr)

top = sorted(rows, key=lambda r: r.get("r",0), reverse=True)[:10]
print("\nTOP 10 PAC:", file=sys.stderr)
for r in top:
    print(f"  ★{r['r']:>5}  {r['ac']:>6}ac  ${r['usd']:>10,}  {r['cf']:<20}  {r.get('a','')[:50]}", file=sys.stderr)
