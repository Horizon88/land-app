"""Data-quality pass over docs/listings.json.

Fixes the error classes found in the Aug-2026 audit:

  1. Duplicate URLs (92 urls / 274 extra rows) — keep the richest row per URL
  2. cf "British Columbia" — a region, not a country — folded into Canada
  3. Coordinates outside the claimed country:
       - JamesEdition slug-tagged rows (je-tahiti / je-samoa / je-new-caledonia
         etc.) whose listings are actually elsewhere (Porto Cervo villa tagged
         Samoa, Lake Austin estate tagged French Polynesia) → dropped
       - USA rows mislabelled Canada (Columbus OH tagged Muskoka-ON) and vice
         versa → country reassigned, bogus region cleared
  4. Placeholder acreage (JE scrape default 0.15 / 0.25 ac when the ad has no
     land size) — produces garbage $/m² (e.g. villa price ÷ 607 m² default).
     Marked area_est=true and upm nulled so they can't pollute comps/sorts.
  5. upm recomputed from usd/m2 everywhere else (293 rows were inconsistent)
  6. ac recomputed from m2 (single source of truth)
  7. Price sanity: drop rows with no price, < $1,000, or > $500M (the $10.7B
     fazwaz misparse), and rows with no coordinates (map app is coord-centric)

Idempotent: safe to re-run. Prints a summary of what changed.
"""
import json, re, sys
from collections import Counter

PATH = '/home/user/land-app/docs/listings.json'

# lat_min, lat_max, lon_min, lon_max  (wrap=True → box crosses the antimeridian)
BOUNDS = {
    'USA':              (18.0, 72.0, -180.0, -66.0),
    'Canada':           (41.5, 84.0, -141.1, -52.0),
    'Portugal':         (32.0, 42.2, -31.5, -6.1),
    'Chile':            (-56.2, -17.4, -80.9, -66.0),
    'Thailand':         (5.5, 20.6, 97.3, 105.7),
    'Japan':            (24.0, 45.7, 122.9, 146.1),
    'Poland':           (49.0, 55.0, 14.1, 24.2),
    'Romania':          (43.6, 48.3, 20.2, 29.8),
    'New Zealand':      (-47.4, -34.3, 166.3, 178.7),
    'Turkey':           (35.8, 42.2, 25.6, 44.9),
    'Austria':          (46.3, 49.1, 9.5, 17.2),
    'Switzerland':      (45.7, 47.9, 5.9, 10.6),
    'French Polynesia': (-28.0, -7.5, -155.0, -134.0),
    'Fiji':             (-21.1, -12.4, 176.0, -178.0),   # wraps
    'Georgia':          (41.0, 43.6, 39.9, 46.8),
    'New Caledonia':    (-23.0, -19.0, 163.5, 168.2),
    'Vanuatu':          (-20.3, -13.0, 166.5, 170.3),
    'Malaysia':         (0.8, 7.4, 99.6, 119.3),
    'Kiribati':         (-11.5, 5.0, 169.0, -150.0),     # wraps
    'Tonga':            (-22.4, -15.5, -176.3, -173.7),
    'Micronesia':       (1.0, 10.1, 137.2, 163.1),
    'Samoa':            (-14.1, -13.4, -172.9, -171.3),
    'Palau':            (2.8, 8.5, 131.1, 134.7),
    'Marshall Islands': (4.5, 14.8, 160.7, 172.2),
    'Papua New Guinea': (-11.7, -0.8, 140.8, 156.0),
    'Australia':        (-43.7, -10.0, 112.9, 153.7),
    'Indonesia':        (-11.0, 6.0, 95.0, 141.0),
    'Argentina':        (-55.1, -21.7, -73.6, -53.6),
}
WRAP = {'Fiji', 'Kiribati'}

def in_bounds(cf, lat, lon):
    b = BOUNDS.get(cf)
    if not b:
        return True  # unknown country — don't judge
    la0, la1, lo0, lo1 = b
    if not (la0 <= lat <= la1):
        return False
    if cf in WRAP:
        return lon >= lo0 or lon <= lo1
    return lo0 <= lon <= lo1

def src(r):
    rb = r.get('rb', '') or ''
    return rb.split('+')[0] if rb.startswith('src:') else ''

def richness(r):
    """Tie-break for duplicate URLs — prefer the row carrying more info."""
    return (len(r.get('imgs') or []), 1 if r.get('name') else 0,
            1 if r.get('v') else 0, len(r.get('rb', '') or ''))

d = json.load(open(PATH))
n0 = len(d)
dropped = Counter()
fixed = Counter()

# ── 1. hard drops: price / coords sanity ─────────────────────────────
keep = []
for r in d:
    usd = r.get('usd') or 0
    # abandoned-ski overlay rows are point-of-interest data, not listings —
    # they legitimately carry no price
    is_poi = r.get('tp') == 'abandoned_ski' or (r.get('rb', '') or '').startswith('closed-ski')
    if usd < 1000 and not is_poi:
        dropped['no_or_junk_price'] += 1
        continue
    if usd > 500_000_000:
        dropped['price_over_500M'] += 1
        continue
    if r.get('lat') is None or r.get('lon') is None:
        dropped['no_coords'] += 1
        continue
    if abs(r['lat']) > 90 or abs(r['lon']) > 180:
        dropped['invalid_coords'] += 1
        continue
    keep.append(r)
d = keep

# ── 2. British Columbia is a region of Canada ────────────────────────
for r in d:
    if r.get('cf') == 'British Columbia':
        r['cf'] = 'Canada'
        if not r.get('rg') or r['rg'] == 'British Columbia':
            r['rg'] = 'BC'
        fixed['bc_folded_into_canada'] += 1

# ── 3. coordinate / country agreement ────────────────────────────────
keep = []
for r in d:
    cf, lat, lon = r.get('cf'), r['lat'], r['lon']
    if in_bounds(cf, lat, lon):
        keep.append(r)
        continue
    # USA ↔ Canada mislabels: trust the coordinates
    if cf == 'Canada' and in_bounds('USA', lat, lon):
        r['cf'] = 'USA'; r['rg'] = ''
        fixed['canada_to_usa'] += 1
        keep.append(r); continue
    if cf == 'USA' and in_bounds('Canada', lat, lon):
        r['cf'] = 'Canada'; r['rg'] = ''
        fixed['usa_to_canada'] += 1
        keep.append(r); continue
    # JamesEdition slug-tagged rows: location untrustworthy → drop
    if src(r).startswith('src:je-'):
        dropped[f'je_geo_mismatch ({cf})'] += 1
        continue
    # anything else: try to relabel to whichever country the point is in
    hit = next((c for c in BOUNDS if in_bounds(c, lat, lon)), None)
    if hit:
        r['cf'] = hit; r['rg'] = r.get('rg') or ''
        fixed['relabelled_by_coords'] += 1
        keep.append(r)
    else:
        dropped[f'geo_mismatch ({cf})'] += 1
d = keep

# ── 4. duplicate URLs — keep the richest row ─────────────────────────
# (POI rows exempt: closed ski areas share rounded OSM links, so dozens of
#  distinct sites legitimately carry the same URL)
by_url = {}
no_url = []
for r in d:
    u = r.get('u')
    if not u or r.get('tp') == 'abandoned_ski' or (r.get('rb', '') or '').startswith('closed-ski'):
        no_url.append(r); continue
    prev = by_url.get(u)
    if prev is None or richness(r) > richness(prev):
        if prev is not None:
            dropped['dup_url'] += 1
        by_url[u] = r
    else:
        dropped['dup_url'] += 1
d = list(by_url.values()) + no_url

# ── 5. placeholder acreage + upm/ac consistency ──────────────────────
for r in d:
    m2, usd = r.get('m2'), r.get('usd')
    placeholder = src(r).startswith('src:je-') and r.get('ac') in (0.15, 0.25)
    if placeholder:
        r['area_est'] = True
        if r.get('upm') is not None:
            r['upm'] = None
            fixed['upm_nulled_placeholder_area'] += 1
        continue
    if m2 and m2 > 0 and usd:
        raw = usd / m2
        new_upm = round(raw, 3 if raw < 1 else (2 if raw < 10 else 1))  # cheap rural land needs decimals
        if r.get('upm') != new_upm:
            r['upm'] = new_upm
            fixed['upm_recomputed'] += 1
        new_ac = round(m2 / 4046.86, 3)
        if r.get('ac') != new_ac:
            r['ac'] = new_ac
            fixed['ac_recomputed'] += 1

# ── 5b. area plausibility ────────────────────────────────────────────
# Catch listing-side size garbage (e.g. a $935k Samut Sakhon lot claiming
# 100,000,000 m² — FazWaz agent typo; Portuguese "16,75 hectares" parsed as
# 1,675 ha).  A row is suspect when its $/m² sits >300× below the country
# median AND the tract is >100,000 m².  Repair from the listing name when it
# states a size; quarantine to docs/quarantine.json when the implied price is
# absurd (<$400/acre); otherwise keep but null upm and flag area_est.
import statistics

def _num(s):
    """Parse a number that may use pt/es decimal commas."""
    s = s.strip()
    if ',' in s and '.' in s:
        s = s.replace(',', '') if s.rindex('.') > s.rindex(',') else s.replace('.', '').replace(',', '.')
    elif ',' in s:
        head, _, tail = s.rpartition(',')
        s = s.replace(',', '') if len(tail) == 3 else s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None

def area_from_name(name):
    """m² stated in the listing title, or None."""
    if not name:
        return None
    for pat, mult in ((r'([\d.,]+)\s*hect', 10000), (r'([\d.,]+)\s*ha\b', 10000),
                      (r'([\d.,]+)\s*acres?\b', 4046.86), (r'([\d.,]+)\s*rai\b', 1600),
                      (r'([\d.,]+)\s*(?:m²|m2\b|sqm)', 1)):
        m = re.search(pat, name, re.I)
        if m:
            v = _num(m.group(1))
            if v and v > 0:
                return v * mult
    return None

_upms = {}
for r in d:
    if r.get('upm') and r.get('tp') != 'abandoned_ski':
        _upms.setdefault(r['cf'], []).append(r['upm'])
_med = {cf: statistics.median(v) for cf, v in _upms.items() if len(v) >= 20}

quarantine = []
keep = []
for r in d:
    upm, m2, usd = r.get('upm'), r.get('m2') or 0, r.get('usd') or 0
    med = _med.get(r.get('cf'))
    suspect = (med and upm is not None and m2 > 100_000 and upm < med / 300
               and r.get('tp') != 'abandoned_ski')
    if not suspect:
        keep.append(r)
        continue
    stated = area_from_name(r.get('name'))
    if stated and stated > 50 and (m2 / stated > 5 or stated / m2 > 5):
        # listing title states the real size — trust it over the size field
        r['m2'] = int(stated) if stated >= 100 else round(stated, 1)
        r['ac'] = round(stated / 4046.86, 3)
        raw = usd / stated
        r['upm'] = round(raw, 3 if raw < 1 else (2 if raw < 10 else 1))
        fixed['area_repaired_from_title'] += 1
        keep.append(r)
    elif usd / (m2 / 4046.86) < 400:
        quarantine.append(r)
        dropped['area_implausible_quarantined'] += 1
    else:
        r['area_est'] = True
        r['upm'] = None
        fixed['area_suspect_upm_nulled'] += 1
        keep.append(r)
d = keep
if quarantine:
    qpath = PATH.replace('listings.json', 'quarantine.json')
    try:
        prev = {q.get('u'): q for q in json.load(open(qpath))}
    except Exception:
        prev = {}
    for q in quarantine:
        prev[q.get('u')] = q
    json.dump(list(prev.values()), open(qpath, 'w'), indent=1)

# ── 6. payload slimming ──────────────────────────────────────────────
# foreign_note: identical country boilerplate repeated per row (1.3 MB) and
# never read by the app — keep one copy per country in a sidecar map.
# img: legacy single-thumb duplicating imgs[0] — fold into imgs and drop.
notes = {}
for r in d:
    fn = r.pop('foreign_note', None)
    if fn and r.get('cf') not in notes:
        notes[r['cf']] = fn
    img = r.pop('img', None)
    if img and not r.get('imgs'):
        r['imgs'] = [img]
if notes:
    json.dump(notes, open(PATH.replace('listings.json', 'foreign_notes.json'), 'w'), indent=1)
    fixed['foreign_note_moved_to_sidecar'] = len(notes)

# ── 6b. value flag: bottom-quartile $/m² within region ───────────────
# `distressed` (the 💎 "cheap for area" flag) was never being set on any
# row — the filter matched nothing. Compute it here: a row is flagged when
# its $/m² sits in the cheapest quartile of a large-enough same-country,
# same-region cohort (≥8 priced comps), so it means "underpriced for where
# it is", distinct from the 🔥 forced-sale `distress` score.
from collections import defaultdict as _dd
_cohort = _dd(list)
for r in d:
    upm = r.get('upm')
    if r.get('cf') and r.get('rg') and isinstance(upm, (int, float)) and upm > 0:
        _cohort[(r['cf'], r['rg'])].append(upm)
_q1 = {}
for key, vals in _cohort.items():
    if len(vals) >= 8:
        vs = sorted(vals)
        _q1[key] = vs[len(vs) // 4]   # 25th percentile
_flagged = 0
for r in d:
    upm = r.get('upm')
    key = (r.get('cf'), r.get('rg'))
    if key in _q1 and isinstance(upm, (int, float)) and upm > 0 and upm <= _q1[key]:
        r['distressed'] = True
        _flagged += 1
    elif r.get('distressed'):
        r.pop('distressed', None)   # clear stale flags if price/region moved
if _flagged:
    fixed['value_flag_bottom_quartile'] = _flagged

# ── 6c. stable plot code + Thai units (rai, ฿/rai, ฿/talang-wah) ──────
# `code` is a short human-distinguishable id derived only from the URL, so
# it is STABLE across re-scrapes/re-scores (never renumbers). Thai rows also
# carry rai + baht-denominated per-area prices, the units the buyer thinks in.
import hashlib as _hl
_CC = {'Thailand':'TH','Japan':'JP','Canada':'CA','USA':'US','Portugal':'PT',
       'Chile':'CL','Poland':'PL','Romania':'RO','Indonesia':'ID',
       'New Zealand':'NZ','Argentina':'AR','Turkey':'TR','Austria':'AT',
       'Switzerland':'CH','French Polynesia':'PF','Fiji':'FJ','Georgia':'GE',
       'New Caledonia':'NC','Vanuatu':'VU','Australia':'AU','Grenada':'GD',
       'Malaysia':'MY','Brazil':'BR','France':'FR','United Kingdom':'GB','Costa Rica':'CR','South Africa':'ZA','Panama':'PA','Nicaragua':'NI','Belize':'BZ','El Salvador':'SV','Guatemala':'GT','Honduras':'HN'}
_B32 = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'   # Crockford-ish: no I L O U
def _plot_code(url, cf):
    n = int(_hl.blake2b((url or '').encode(), digest_size=8).hexdigest(), 16)
    s = ''
    for _ in range(6):                       # 32^6 ≈ 1B keyspace → ~0 collisions
        s = _B32[n % 32] + s; n //= 32
    return f"{_CC.get(cf, 'XX')}-{s}"

_coded = 0; _thai_units = 0
for r in d:
    if r.get('u'):
        r['code'] = _plot_code(r['u'], r.get('cf', '')); _coded += 1
    if r.get('cf') == 'Thailand' and r.get('m2'):
        m2 = r['m2']
        # recover THB: prefer the native list price, else convert from usd
        baht = None
        if str(r.get('cur', '')).upper() == 'THB' and r.get('lp'):
            try: baht = float(str(r['lp']).replace(',', ''))
            except Exception: baht = None
        if not baht and r.get('usd'):
            baht = r['usd'] * 36
        rai = m2 / 1600.0                    # 1 rai = 1600 m²
        r['rai'] = round(rai, 2)
        if baht and rai:
            r['baht'] = int(round(baht))
            r['baht_rai'] = int(round(baht / rai))            # per rai
            r['baht_wah'] = int(round(baht / (m2 / 4.0)))     # per talang wah (1 wah²=4 m²)
            _thai_units += 1
    else:
        for k in ('rai', 'baht', 'baht_rai', 'baht_wah'):
            r.pop(k, None)
if _coded: fixed['plot_code_assigned'] = _coded
if _thai_units: fixed['thai_units_added'] = _thai_units

# ── 7. number normalization (payload size) ───────────────────────────
# full-precision floats bloat the 18 MB payload; 5-decimal coords ≈ 1 m
for r in d:
    if isinstance(r.get('lat'), float): r['lat'] = round(r['lat'], 5)
    if isinstance(r.get('lon'), float): r['lon'] = round(r['lon'], 5)
    m2 = r.get('m2')
    if isinstance(m2, float):
        r['m2'] = int(m2) if m2 >= 100 else round(m2, 1)
    if isinstance(r.get('usd'), float): r['usd'] = int(r['usd'])
    if isinstance(r.get('r'), float): r['r'] = round(r['r'], 1)

d.sort(key=lambda r: r.get('r', 0), reverse=True)
json.dump(d, open(PATH, 'w'), separators=(',', ':'))

print(f'{n0} → {len(d)} rows ({n0 - len(d)} removed)', file=sys.stderr)
print('\ndropped:', file=sys.stderr)
for k, v in dropped.most_common():
    print(f'  {k}: {v}', file=sys.stderr)
print('\nfixed in place:', file=sys.stderr)
for k, v in fixed.most_common():
    print(f'  {k}: {v}', file=sys.stderr)
print('\ncountries now:', Counter(r["cf"] for r in d).most_common(), file=sys.stderr)
