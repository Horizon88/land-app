"""Merge LandSearch expansion (Pacific + Southeast + Maine + HI + AK + ON) into listings.json."""
import json, math, sys, statistics
from collections import Counter

raw = json.load(open("/tmp/expand_landsearch.json"))
print(f"raw LandSearch expansion: {len(raw)}", file=sys.stderr)

SIZE_TIERS = [(0.1,-25),(0.25,-12),(0.5,0),(1,6),(2.5,14),(5,22),(10,32),(25,44),(50,56),(100,68),(500,80),(float("inf"),92)]
def sb(a):
    for t,b in SIZE_TIERS:
        if a < t: return b
    return 92

# US + Canadian ski resorts already curated in ski_resorts.json — pull minimal subset here
SKI = [
    # PNW
    ('Whistler',50.115,-122.955),('Mt-Baker-WA',48.858,-121.679),
    ('Crystal-Mtn-WA',46.933,-121.475),('Bachelor-OR',43.980,-121.688),
    ('Mt-Hood-OR',45.331,-121.712),('Timberline-OR',45.331,-121.712),
    # California
    ('Squaw-Valley',39.196,-120.235),('Heavenly',38.936,-119.940),
    ('Mammoth',37.628,-119.032),('Big-Bear',34.229,-116.912),
    # Ontario
    ('Blue-Mountain-ON',44.500,-80.320),('Mont-Tremblant',46.212,-74.585),
    # Alaska
    ('Alyeska',60.973,-149.100),
    # East
    ('Sugarloaf-ME',45.031,-70.313),('Sunday-River-ME',44.470,-70.860),
    ('Killington-VT',43.605,-72.795),('Stowe-VT',44.530,-72.782),
    ('Bretton-Woods-NH',44.259,-71.478),
]
def hav(a,b,c,d):
    R = 6371
    dl = math.radians(c-a); dlo = math.radians(d-b)
    h = math.sin(dl/2)**2 + math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

# Coarse coast anchors — one per major coastline block
COAST = [
    # Pacific
    (48.5,-124.7),(47.9,-124.6),(46.9,-124.1),(46.2,-124.0),(45.5,-123.9),
    (44.7,-124.1),(43.4,-124.3),(42.4,-124.4),(41.7,-124.2),(40.7,-124.2),
    (39.4,-123.8),(38.8,-123.7),(38.0,-122.8),(37.5,-122.5),(37.0,-122.2),
    (36.5,-121.9),(36.0,-121.5),(35.6,-121.1),(35.0,-120.7),(34.7,-120.5),
    (34.4,-120.0),(34.0,-118.7),(33.6,-118.0),(32.8,-117.3),
    # Hawaii
    (19.7,-155.5),(20.9,-156.6),(21.3,-157.9),(22.1,-159.5),
    # Alaska
    (55.3,-131.6),(60.9,-149.4),
    # Northeast US
    (44.8,-67.0),(44.4,-68.2),(43.9,-69.6),(43.0,-70.7),(42.7,-70.8),(41.5,-70.6),
    (41.2,-71.5),(41.3,-71.9),(41.0,-72.3),
    # SE US
    (36.5,-75.9),(35.9,-75.6),(34.7,-76.7),(34.2,-77.9),(33.9,-78.4),
    (32.8,-79.9),(32.1,-80.8),(31.4,-81.3),(30.7,-81.6),
    (29.9,-81.3),(24.6,-81.4),(30.4,-86.6),
    # Great Lakes (approx)
    (44.9,-85.7),(45.3,-85.4),
    # Canada Atlantic
    (46.2,-63.1),(45.3,-63.0),(45.9,-66.1),(47.6,-52.7),
    # Ontario Georgian Bay
    (44.6,-80.3),(45.2,-80.5),
    # Kootenays / BC lakes (freshwater but keep)
]

# Global median $/m² for value scoring — pull from existing dataset
existing_all = json.load(open("/home/user/land-app/docs/listings.json"))
usa_ca = [r for r in existing_all if r.get('cf') in ('USA','Canada','British Columbia') and r.get('upm')]
med_upm = statistics.median(r['upm'] for r in usa_ca) if usa_ca else 25

rows = []
for r in raw:
    ac = r.get("acres") or 0
    if ac < 0.1: continue
    m2 = int(ac * 4046.86)
    usd = int(r.get("price_usd") or 0)
    if usd < 5000: continue
    upm = round(usd / m2, 1) if m2 else 0
    lat = r.get("lat"); lon = r.get("lon")
    if not lat or not lon: continue

    rb = ["src:landsearch-exp"]
    score = 16; rb.append("acc+16")
    sbn = sb(ac); score += sbn; rb.append(f"size{'+' if sbn>=0 else ''}{sbn}")

    if med_upm and upm:
        ratio = upm / med_upm
        if ratio < 0.4: vb = 10
        elif ratio < 0.7: vb = 6
        elif ratio < 1.0: vb = 3
        elif ratio < 1.5: vb = 0
        elif ratio < 2.5: vb = -3
        else: vb = -6
        if vb: score += vb; rb.append(f"val{'+' if vb>0 else ''}{vb}")

    coast_km = round(min(hav(lat, lon, a, b) for a,b in COAST), 2)
    if coast_km <= 0.5: score += 18; rb.append("beachfront+18")
    elif coast_km <= 2: score += 12; rb.append("coast≤2km+12")
    elif coast_km <= 10: score += 6; rb.append("coast≤10km+6")

    ski_km = min(hav(lat, lon, la, lo) for _, la, lo in SKI)
    ski_r = min(SKI, key=lambda s: hav(lat, lon, s[1], s[2]))[0]
    if ski_km <= 0.5: score += 15; rb.append("ski-in+15")
    elif ski_km <= 2: score += 10; rb.append("ski≤2km+10")
    elif ski_km <= 10: score += 5; rb.append("ski≤10km+5")
    if ac >= 10 and 0.5 < ski_km <= 20: score += 8; rb.append("rope-tow+8")
    if ac >= 5 and ski_km <= 30: score += 8; rb.append("sled+8")

    rows.append({
        "tp":"land","cf":r["country"],
        "r": round(score,1),
        "rg": r["region"],
        "a": (r.get("loc") or "").split(",")[0][:40],
        "ac": ac, "m2": m2, "usd": usd, "upm": upm,
        "v":"","el":"",
        "t":"Fee simple (USA/CA freehold)",
        "lat": lat, "lon": lon,
        "cur":"USD","lp":str(usd),
        "rb": "+".join(rb),
        "img":"","imgs":[],
        "u": r["url"],
        "apt":"","apt_km":None,
        "name": r.get("title","")[:140],
        "ski_km": round(ski_km,2), "ski_r": ski_r,
        "coast_km": coast_km,
        "foreign_friction": 0,
        "foreign_note":"US/CA: freehold OK for non-residents (some state-specific ag-land restrictions).",
    })

existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing = [e for e in existing if "src:landsearch-exp" not in (e.get("rb","") or "")]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda r: r.get("r",0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json","w"))
print(f"merged: {len(rows)} new rows; total {len(merged)}", file=sys.stderr)

by = Counter(r["rg"] for r in rows)
print(f"top regions:", by.most_common(15), file=sys.stderr)
