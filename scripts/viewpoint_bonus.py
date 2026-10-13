"""Bonus scoring for land near iconic viewpoints.

For land within a hero-view basin, add a rating bonus + a viewpoint tag
that surfaces in the popover ("👁 Samet Nangshe basin — 8km").

Bonus schedule per viewpoint:
  ≤ 3 km : +25   (same ridge — direct view is likely)
  ≤ 10 km: +18   (in the view basin — you probably see it from higher ground)
  ≤ 25 km: +10   (same karst/island system — shares the aesthetic)
  ≤ 40 km: +5    (same day-trip catchment)

Add more viewpoints by appending to VIEWPOINTS. Each entry:
  (name, lat, lng, country_filter or None)

To rerun after adding a viewpoint, just execute this script again — it
strips any existing viewpoint tags (starting with "vp:") before re-scoring
so it's idempotent.
"""
import json, math, re

LISTINGS = "/home/user/land-app/docs/listings.json"

VIEWPOINTS = [
    # (name, lat, lng, country_filter)  — country_filter None = apply to any listing
    ("Samet Nangshe",   8.3628, 98.5122, "Thailand"),
    ("Ao Nang",         8.0333, 98.8250, "Thailand"),  # Ao Nang viewpoint + beach
    ("Railay",          8.0114, 98.8402, "Thailand"),  # limestone peninsula, west coast
]

def hav(a, b, c, d):
    R = 6371
    dl = math.radians(c-a); dlo = math.radians(d-b)
    h = math.sin(dl/2)**2 + math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

listings = json.load(open(LISTINGS))
print(f"listings: {len(listings)}, viewpoints: {len(VIEWPOINTS)}")

# Strip any previous viewpoint bonuses/tags for idempotency
VP_TAG = re.compile(r'\+vp:[^+]+\+\d+')
BONUS_TAG = re.compile(r'\+vp≤\d+km\+\d+')
n_stripped = 0
for r in listings:
    old_rb = r.get("rb","") or ""
    # Compute old vp bonus to subtract
    old_bonus = 0
    for m in re.finditer(r'\+vp≤(\d+)km\+(\d+)', old_rb):
        old_bonus += int(m.group(2))
    new_rb = BONUS_TAG.sub("", VP_TAG.sub("", old_rb))
    if new_rb != old_rb:
        r["rb"] = new_rb
        r["r"] = round((r.get("r") or 0) - old_bonus, 1)
        n_stripped += 1
    # Also clear the field so we can rewrite it
    if "viewpoints" in r:
        del r["viewpoints"]
print(f"stripped previous vp bonuses on {n_stripped} listings")

n_applied = 0
for r in listings:
    lat = r.get("lat"); lng = r.get("lon")
    if not lat or not lng: continue
    matches = []
    for name, vlat, vlng, cf_filter in VIEWPOINTS:
        if cf_filter and r.get("cf") != cf_filter: continue
        d = hav(lat, lng, vlat, vlng)
        if d > 40: continue
        matches.append((name, round(d, 1)))
    if not matches: continue
    # Sort closest first
    matches.sort(key=lambda x: x[1])
    bonus = 0
    tags = []
    for name, d in matches:
        if d <= 3:   b = 25
        elif d <= 10: b = 18
        elif d <= 25: b = 10
        elif d <= 40: b = 5
        else: continue
        bonus += b
        tags.append(f"vp≤{int(d) if d>=1 else 1}km+{b}")
    if not bonus: continue
    r["r"] = round((r.get("r") or 0) + bonus, 1)
    rb = r.get("rb","") or ""
    # Only emit detail tags (vp≤Xkm+N); summary lives in r["viewpoints"] for
    # display. This keeps the client-side weight parser from double-counting.
    r["rb"] = rb + ("+" if rb and not rb.endswith("+") else "") + "+".join(tags)
    r["viewpoints"] = [{"name": n, "km": d} for n, d in matches]
    n_applied += 1

json.dump(listings, open(LISTINGS, "w"))
print(f"applied viewpoint bonus to {n_applied} listings")

# Show the top 10 that got boosted
boosted = sorted([r for r in listings if r.get("viewpoints")], key=lambda r: r.get("r",0), reverse=True)[:10]
for r in boosted:
    vps = ", ".join(f"{v['name']} {v['km']}km" for v in r["viewpoints"])
    print(f"  ★{r['r']:>5}  {r.get('ac',0):>6}ac  ${r.get('usd',0):>10,}  {r.get('rg',''):<12}  {vps}  |  {(r.get('name','') or '')[:50]}")
