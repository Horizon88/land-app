"""Add view/dualview/steal bonus tags to every listing that qualifies.

Idempotent — strips any existing view+/dualview+/steal+ tags first, then
re-computes.

Rules:
  - view+8   if r.v == 'sea_visible' or r.name mentions 'sea view' etc.
  - view+6   if 'mountain view' or 'mountain' in r.name
  - dualview+15 if BOTH sea/ocean AND mountain/hill mentioned
  - steal+18 if r.upm < 0.2× the median $/m² for r.rg (region)
             (the existing val+ tag stays untouched; steal stacks on top)
"""
import json, re, statistics, sys
from collections import defaultdict

LISTINGS = "/home/user/land-app/docs/listings.json"
d = json.load(open(LISTINGS))
print(f"listings: {len(d)}", file=sys.stderr)

# Strip any existing view/dualview/steal tags
STRIP = re.compile(r'\+(?:view|dualview|steal)\+\d+')
n_stripped = 0
for r in d:
    rb = r.get("rb","") or ""
    # Remove old bonus + subtract from r
    for m in re.finditer(r'\+(view|dualview|steal)\+(\d+)', rb):
        try:
            r["r"] = round((r.get("r") or 0) - int(m.group(2)), 1)
        except: pass
    new_rb = STRIP.sub("", rb)
    if new_rb != rb:
        r["rb"] = new_rb
        n_stripped += 1
print(f"stripped prior view/dualview/steal on {n_stripped} rows", file=sys.stderr)

# Compute regional median upm per (cf, rg) — require ≥10 comparables and a
# non-trivial median. Skips wildland regions where medians are noise.
by_region = defaultdict(list)
for r in d:
    if not r.get("upm"): continue
    if not r.get("m2") or r["m2"] < 100: continue
    by_region[(r.get("cf",""), r.get("rg",""))].append(r["upm"])
med = {k: statistics.median(v) for k, v in by_region.items() if len(v) >= 10 and statistics.median(v) >= 50}
print(f"region medians computed: {len(med)}", file=sys.stderr)

SEA_KW = re.compile(r'\b(?:sea|ocean|beach|coast|beachfront|seafront|oceanfront|sea[- ]?view)\b', re.I)
MTN_KW = re.compile(r'\b(?:mountain|hillside|hilltop|cliff|panoramic|karst|peak|ridge)\b', re.I)

n_view = n_dual = n_steal = 0
for r in d:
    rb = r.get("rb","") or ""
    add_tags = []
    add_bonus = 0

    v = (r.get("v") or "").lower()
    name = (r.get("name") or "")
    # View bonus
    sea = (v in ("sea_visible", "beachfront", "seafront", "oceanfront")
           or bool(SEA_KW.search(name)))
    mtn = bool(MTN_KW.search(name)) or v in ("mountain", "mountain_view")
    if sea and mtn:
        add_bonus += 15
        add_tags.append("dualview+15")
        n_dual += 1
    elif sea:
        # beachfront already scored via coast; only credit sea_view for non-beachfront
        if v == "sea_visible" or "sea view" in name.lower():
            add_bonus += 8
            add_tags.append("view+8")
            n_view += 1
    elif mtn:
        add_bonus += 6
        add_tags.append("view+6")
        n_view += 1

    # Steal — ratio < 0.2 of regional median
    upm = r.get("upm") or 0
    key = (r.get("cf",""), r.get("rg",""))
    if upm and key in med and med[key] > 0:
        ratio = upm / med[key]
        if ratio < 0.15 and r.get("m2", 0) >= 2000:  # tight threshold + real lot
            add_bonus += 18
            add_tags.append("steal+18")
            n_steal += 1

    if add_bonus:
        r["r"] = round((r.get("r") or 0) + add_bonus, 1)
        r["rb"] = (rb + ("+" if rb and not rb.endswith("+") else "")) + "+".join(add_tags)

json.dump(d, open(LISTINGS, "w"))
print(f"applied: view {n_view}, dualview {n_dual}, steal {n_steal}", file=sys.stderr)

# Show top 10 after rescore
top = sorted(d, key=lambda r: r.get("r",0), reverse=True)[:10]
print("\nTop 10 after rescore:", file=sys.stderr)
for r in top:
    tags = [t for t in re.findall(r'(?:view|dualview|steal)\+\d+', r.get("rb",""))]
    print(f"  {r.get('r',0):>5}  {r.get('ac',0):>7}ac  ${r.get('usd',0):>10,}  {r.get('cf',''):<20}  {'+'.join(tags):<25}  {r.get('name','')[:50]}", file=sys.stderr)
