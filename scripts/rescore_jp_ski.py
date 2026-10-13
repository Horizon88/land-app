"""Recompute ski_km + ski_r + score bonuses for every listing after
expanding the ski_resorts.json curation. Only Japan is fully redone here;
other countries are re-checked to ensure ski distance is against the
full 152-resort set.

For each listing:
  - Find nearest ski resort → set ski_km, ski_r
  - Remove old ski bonuses from score (ski-in+15, ski≤2km+10, ski≤10km+5, rope-tow+8, sled+8)
  - Add fresh bonuses based on new ski_km
  - Same for rb tag string
"""
import json, math, re

REPO_LISTINGS = "/home/user/land-app/docs/listings.json"

def hav(a, b, c, d):
    R = 6371
    dl = math.radians(c-a); dlo = math.radians(d-b)
    h = math.sin(dl/2)**2 + math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

SKI = json.load(open("/tmp/ski_resorts.json"))
listings = json.load(open(REPO_LISTINGS))
print(f"listings: {len(listings)}, ski resorts: {len(SKI)}")

# Old ski bonus tags to strip from rb
SKI_TAGS = re.compile(r'\+(ski-in\+15|ski≤2km\+10|ski≤10km\+5|rope-tow\+8|sled\+8|ski>10km\+0)')

n_updated_ski = 0
n_new_near_ski = 0
for r in listings:
    lat = r.get("lat"); lng = r.get("lon")
    if not lat or not lng: continue
    ac = r.get("ac") or 0
    # Skip abandoned_ski (they ARE ski entries) and non-land unless they have lat/lng
    if r.get("tp") == "abandoned_ski": continue

    # Find nearest resort
    best = min((hav(lat, lng, s["lat"], s["lon"]), s["name"]) for s in SKI)
    new_ski_km = round(best[0], 2)
    new_ski_r = best[1]

    old_km = r.get("ski_km")
    if old_km is None or abs((old_km or 0) - new_ski_km) > 0.1:
        n_updated_ski += 1
        if (old_km is None or old_km > 8) and new_ski_km <= 8:
            n_new_near_ski += 1

    r["ski_km"] = new_ski_km
    r["ski_r"] = new_ski_r

    # Strip old ski bonuses from rb string
    rb = r.get("rb","") or ""
    # Compute old ski contribution to subtract
    old_bonus = 0
    if "ski-in+15" in rb: old_bonus += 15
    if "ski≤2km+10" in rb: old_bonus += 10
    if "ski≤10km+5" in rb: old_bonus += 5
    if "rope-tow+8" in rb: old_bonus += 8
    if "sled+8" in rb: old_bonus += 8
    rb = SKI_TAGS.sub("", rb)

    # Compute new bonus
    new_bonus = 0
    new_tags = []
    if new_ski_km <= 0.5: new_bonus += 15; new_tags.append("ski-in+15")
    elif new_ski_km <= 2: new_bonus += 10; new_tags.append("ski≤2km+10")
    elif new_ski_km <= 10: new_bonus += 5; new_tags.append("ski≤10km+5")
    if ac >= 10 and 0.5 < new_ski_km <= 20:
        new_bonus += 8; new_tags.append("rope-tow+8")
    if ac >= 5 and new_ski_km <= 30:
        new_bonus += 8; new_tags.append("sled+8")

    # Append new tags
    if new_tags:
        rb = rb.rstrip("+") + "+" + "+".join(new_tags)
    r["rb"] = rb

    # Adjust score by delta
    old_r = r.get("r") or 0
    r["r"] = round(old_r - old_bonus + new_bonus, 1)

json.dump(listings, open(REPO_LISTINGS, "w"))
print(f"updated ski_km on {n_updated_ski} listings; {n_new_near_ski} newly ≤8km from ski")

# Report Japan ≤8km change
jp_near = sum(1 for r in listings if r.get("cf")=="Japan" and (r.get("ski_km") or 9999) <= 8)
print(f"Japan ≤8km now: {jp_near}")
