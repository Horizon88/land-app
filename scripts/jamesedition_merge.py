"""Merge JamesEdition Pacific listings into listings.json."""
import json, math, sys
from collections import Counter

raw = json.load(open("/tmp/jamesedition_pacific.json"))
print(f"raw JE rows: {len(raw)}", file=sys.stderr)

SIZE_TIERS = [(0.1,-25),(0.25,-12),(0.5,0),(1,6),(2.5,14),(5,22),(10,32),(25,44),(50,56),(100,68),(500,80),(float("inf"),92)]
def sb(ac):
    for t,b in SIZE_TIERS:
        if ac < t: return b
    return 92

rows = []
for r in raw:
    ac = r.get("acres") or 0.25   # default 0.25 ac for JE listings without land size
    if ac < 0.05: continue
    m2 = int(ac * 4046.86)
    usd = int(r.get("price_usd") or 0)
    if usd < 10000: continue
    upm = round(usd / m2, 1) if m2 else 0

    rbits = [f"src:je-{r['slug']}"]
    score = 16; rbits.append("acc+16")
    b = sb(ac); score += b; rbits.append(f"size{'+' if b>=0 else ''}{b}")
    score += 18; rbits.append("beachfront+18")   # JE Pacific = coastal luxury
    ff = r["foreign_friction"]
    if ff: score += ff; rbits.append(f"foreign_{r['slug']}{'+' if ff>0 else ''}{ff}")

    rows.append({
        "tp": "land", "cf": r["country"],
        "r": round(score, 1),
        "rg": r.get("loc","").split(",")[-1].strip()[:20] or r["country"],
        "a": r.get("loc","")[:40],
        "ac": round(ac, 3), "m2": m2, "usd": usd, "upm": upm,
        "v": "beachfront", "el": "",
        "t": "Freehold or long-term lease (see foreign_note)",
        "lat": r.get("lat"), "lon": r.get("lng"),
        "cur": "USD", "lp": str(usd),
        "rb": "+".join(rbits),
        "img": r.get("img","") or "",
        "imgs": [r["img"]] if r.get("img") else [],
        "u": r["url"],
        "apt":"","apt_km":None,
        "name": (r.get("title","") or "")[:140],
        "ski_km": None, "coast_km": 0.5,
        "foreign_friction": r["foreign_friction"],
        "foreign_note": r["foreign_note"],
        "pacific": True,
        "luxury": True,
    })

# Merge — strip prior JE rows (src:je-*) OR realtor-pacific rows so we can
# fully re-merge each run without duplicates
existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing = [e for e in existing if "src:je-" not in (e.get("rb","") or "")]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda r: r.get("r",0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json","w"))
print(f"merged: {len(rows)} new JE rows; total {len(merged)}", file=sys.stderr)

by_cf = Counter(r["cf"] for r in rows)
print(f"by country: {by_cf.most_common()}", file=sys.stderr)
top = sorted(rows, key=lambda r: r.get("r",0), reverse=True)[:12]
print("\nTOP 12 JE:", file=sys.stderr)
for r in top:
    print(f"  ★{r['r']:>5}  {r['ac']:>6}ac  ${r['usd']:>12,}  {r['cf']:<20}  {r.get('name','')[:50]}", file=sys.stderr)
