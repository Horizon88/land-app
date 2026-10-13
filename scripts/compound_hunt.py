"""Compound Hunt — 100+ ac North American mountain compounds ≤$20M ≤30 min elite ski.

Scores each candidate on 8 dimensions (0-10 each):

  Ski          proximity + elite-resort quality
  Airstrip     nearest FAA/Nav-Canada airport + terrain flatness proxy
  Heli         landing suitability (elevation, valley floor)
  Snow         historical annual inches at nearest elite resort
  Carry        annual property tax cost as % of ask (lower = higher score)
  Permitting   state/province build-permit ease
  Price        inverse of ask (cheaper = higher, normalized against $20M)
  Total        sum

Emits:
  /home/user/land-app/docs/compounds.json     — for UI overlay
  Prints ranked table to stdout
"""
import json, math, sys

d = json.load(open('/home/user/land-app/docs/listings.json'))

# Elite resorts: name → (annual_snow_inches, tier)
ELITE_SKI = {
    # Colorado
    'Aspen': (300, 10), 'Aspen-CO': (300, 10), 'Aspen Snowmass': (300, 10),
    'Snowmass': (300, 10), 'Vail': (354, 10), 'Vail-CO': (354, 10),
    'Beaver-Creek': (325, 9), 'Crested-Butte': (300, 9), 'Crested-Butte-CO': (300, 9),
    'Telluride': (300, 10), 'Steamboat': (349, 10), 'Steamboat-CO': (349, 10),
    'Wolf-Creek': (430, 8), 'Winter-Park': (327, 8),
    # Utah
    'Park City': (355, 10), 'Park-City': (355, 10), 'Park-City-UT': (355, 10),
    'Deer-Valley': (300, 10), 'Wasatch-UT': (500, 10),
    'Wasatch': (500, 10), 'Alta': (500, 10), 'Snowbird': (500, 10),
    # Wyoming
    'Jackson Hole': (459, 10), 'Jackson-Hole': (459, 10), 'Jackson-Hole-WY': (459, 10),
    'Grand-Targhee': (500, 9),
    # Montana
    'Big Sky': (400, 10), 'Big-Sky': (400, 10), 'Big-Sky-MT': (400, 10),
    'Yellowstone-Club': (400, 10), 'Bridger-Bowl': (300, 8), 'Whitefish': (330, 8),
    # Idaho
    'Sun Valley': (200, 10), 'Sun-Valley': (200, 10), 'Sun-Valley-ID': (200, 10),
    # California
    'Palisades-Tahoe': (400, 10), 'Squaw-Valley': (400, 10), 'Heavenly': (360, 9),
    'Northstar': (350, 9), 'Mammoth': (400, 10),
    # BC
    'Whistler': (466, 10), 'Whistler-Blackcomb': (466, 10),
    'Revelstoke': (411, 10), 'Kicking-Horse': (295, 9), 'Fernie': (360, 9),
    'Panorama': (200, 8), 'Sun-Peaks': (237, 8), 'Silver-Star': (275, 8),
    # Alberta
    'Banff': (312, 10), 'Lake-Louise': (312, 10),
    'Sunshine-Village': (360, 10), 'Norquay': (300, 8),
}

# State/province → (property_tax_pct, permitting_ease_0_10)
JURIS_TAX = {
    'WY': (0.55, 9),  # Wyoming — lowest tax, easy permits, no state income tax
    'MT': (0.75, 8),  # Montana — low tax, easy permits, some conservation overlay
    'ID': (0.65, 8),  # Idaho — low tax, easy permits
    'UT': (0.55, 6),  # Utah — low tax, permitting stricter in Summit/Wasatch counties
    'CO': (0.55, 4),  # Colorado — low tax BUT county planning is aggressive (Pitkin especially)
    'NV': (0.55, 7),  # Nevada
    'CA': (0.75, 3),  # California — Prop 13 caps but CEQA + coastal commission brutal
    'OR': (0.90, 4),  # Oregon — land-use LCDC statewide restrictive
    'WA': (0.95, 5),
    'HI': (0.30, 3),
    'AK': (1.20, 6),
    'BC': (0.65, 5),  # BC — moderate tax; ALR restricts ag land
    'AB': (0.90, 8),  # Alberta — no PST, easy permits
    'ON': (1.10, 4),
}

def parse_state(rg):
    """Guess state/province abbrev from region string like 'Aspen-CO' or 'Park-City-UT'."""
    m = None
    for st in JURIS_TAX:
        if rg.endswith('-' + st) or rg == st or ' ' + st in rg or '-' + st + '-' in rg:
            return st
    return None

def score_ski(ski_km, ski_r, elite_tier):
    """Ski dimension: closer + more elite = higher. 0-10 scale."""
    # Distance score (0-5): 0km=5, 30km=0
    d = max(0, 5 - (ski_km / 6))
    # Elite tier score (0-5): tier 10 → 5, tier 8 → 3, no elite → 0
    e = max(0, (elite_tier - 5) * 1.25) if elite_tier else 0
    return round(min(10, d + e), 1)

def score_snow(inches):
    """0-10: 200in=5, 400in=8, 500in+=10."""
    if not inches: return 0
    return round(min(10, inches / 50), 1)

def score_carry(usd, tax_pct):
    """Annual tax cost as % of ask. 0-10 (lower cost = higher score)."""
    if not usd or not tax_pct: return 5
    annual_tax = usd * (tax_pct / 100)
    # $10k/yr on $2M = 0.5% → 10; $200k/yr on $20M = 1% → 5
    return round(max(0, min(10, 10 - (tax_pct - 0.3) * 8)), 1)

def score_price(usd):
    """0-10: $20M → 0, $2M → 10, $10M → 5."""
    return round(max(0, min(10, 10 - (usd / 2_000_000))), 1)

def score_airstrip(ac, ski_r):
    """Airstrip proxy: bigger tract + Montana/Wyoming ranch country = higher.
    Heli-only regions (Colorado alpine) get lower airstrip score."""
    base = min(6, ac / 30)  # 30ac base for a 1500ft turf strip → 6 points
    if any(k in (ski_r or '') for k in ('Big-Sky','Yellowstone','Sun Valley','Sun-Valley','Jackson')):
        base += 2  # ranch country
    elif any(k in (ski_r or '') for k in ('Aspen','Vail','Telluride','Beaver')):
        base -= 2  # tight valleys — heli only
    return round(max(0, min(10, base)), 1)

def score_heli(ac, elite_tier):
    """Any 100+ac mountain lot supports heli; elite ski = higher demand."""
    base = min(8, ac / 25)
    if elite_tier >= 9: base += 2
    return round(max(0, min(10, base)), 1)

NA = ('USA','Canada','British Columbia')
cands = [r for r in d if r.get('cf') in NA
         and (r.get('ac') or 0) >= 100
         and (r.get('ski_km') or 999) <= 30
         and 100000 <= (r.get('usd') or 0) <= 20_000_000
         and r.get('lat')]

scored = []
for r in cands:
    rg = r.get('rg','') or ''
    ski_r = r.get('ski_r','') or ''
    # Elite tier lookup
    elite_tier = 0
    snow = 0
    for k, (inches, tier) in ELITE_SKI.items():
        if k in rg or k in ski_r or k.replace('-',' ') in ski_r:
            if tier > elite_tier: elite_tier = tier; snow = inches
    if not elite_tier: continue

    state = parse_state(rg)
    tax_pct, permit = JURIS_TAX.get(state, (0.85, 5))

    s_ski = score_ski(r['ski_km'], ski_r, elite_tier)
    s_air = score_airstrip(r['ac'], ski_r)
    s_hel = score_heli(r['ac'], elite_tier)
    s_snow = score_snow(snow)
    s_car = score_carry(r['usd'], tax_pct)
    s_perm = round(permit, 1)
    s_price = score_price(r['usd'])
    total = round(s_ski + s_air + s_hel + s_snow + s_car + s_perm + s_price, 1)

    scored.append({
        "cf": r['cf'], "state": state, "rg": rg, "ski_r": ski_r,
        "ac": r['ac'], "usd": r['usd'], "ski_km": r['ski_km'],
        "lat": r['lat'], "lon": r['lon'],
        "name": (r.get('name') or '')[:80],
        "url": r.get('u'),
        "score": {
            "ski": s_ski, "airstrip": s_air, "heli": s_hel, "snow": s_snow,
            "carry": s_car, "permit": s_perm, "price": s_price, "total": total
        }
    })

scored.sort(key=lambda x: -x['score']['total'])

# Console print
print(f'\n{len(scored)} compounds passing base filter (100+ac, ≤30km elite ski, ≤$20M)\n')
hdr = f'{"#":<3}{"Ski":>4}{"Air":>4}{"Heli":>5}{"Snow":>5}{"Carry":>6}{"Prm":>4}{"Prc":>4}{"TOT":>5}  {"Ask":<12}{"Ac":>7}  {"State":>5}  {"Resort":<22} {"Name":<50}'
print(hdr)
print('-' * len(hdr))
for i, r in enumerate(scored, 1):
    s = r['score']
    print(f'{i:<3}{s["ski"]:>4}{s["airstrip"]:>4}{s["heli"]:>5}{s["snow"]:>5}{s["carry"]:>6}{s["permit"]:>4}{s["price"]:>4}{s["total"]:>5}  ${r["usd"]:>10,}  {r["ac"]:>6}  {r["state"] or "?":>5}  {r["ski_r"][:21]:<22} {r["name"][:48]}')

json.dump(scored, open('/home/user/land-app/docs/compounds.json', 'w'), indent=2)
print(f'\nWrote docs/compounds.json ({len(scored)} rows)', file=sys.stderr)
