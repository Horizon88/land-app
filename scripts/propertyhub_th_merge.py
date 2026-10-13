"""Merge PropertyHub Thai listings into docs/listings.json."""
import json, math, sys, statistics
from collections import Counter

raw = json.load(open("/tmp/propertyhub_th.json"))
print(f"raw PropertyHub rows: {len(raw)}", file=sys.stderr)

SIZE_TIERS = [(0.1,-25),(0.25,-12),(0.5,0),(1,6),(2.5,14),(5,22),(10,32),(25,44),(50,56),(100,68),(500,80),(float("inf"),92)]
def sb(ac):
    for t,b in SIZE_TIERS:
        if ac < t: return b
    return 92

# Full Thai coast anchors (Andaman + Gulf + Bangkok metro Gulf + Eastern Gulf)
COAST = [
    # Andaman
    (10.0,98.75),(9.5,98.36),(9.0,98.25),(8.5,98.28),(8.2,98.30),(7.9,98.30),
    (7.63,98.60),(7.30,99.10),(7.00,99.35),(6.65,99.65),(6.55,100.10),
    # Southern Gulf
    (6.25,101.4),(7.0,100.6),(7.20,100.60),(8.43,99.96),(9.50,100.00),
    (10.50,99.18),(11.50,99.20),(12.00,99.90),(12.50,99.90),
    # Western Gulf (Hua Hin / Cha-am / Petchaburi)
    (12.57,99.96),(12.80,99.97),(13.11,99.94),
    # Bangkok Gulf
    (13.42,100.00),(13.55,100.27),(13.60,100.60),
    # Eastern Gulf
    (13.36,100.98),(12.92,100.88),(12.66,100.90),(12.68,101.28),
    (12.61,102.10),(12.24,102.51),(12.05,102.35),(11.65,102.55),
]
def hav(a,b,c,d):
    R=6371
    dl=math.radians(c-a); dlo=math.radians(d-b)
    h=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

# Iconic viewpoints (Thai)
VP = [("Samet Nangshe",8.3628,98.5122),("Ao Nang",8.0333,98.8250),("Railay",8.0114,98.8402)]

# Compute median $/m² for value scoring
upms = [r["price_usd"]/r["sqm"] for r in raw if r.get("sqm",0)>100 and r.get("price_usd")]
med_upm = statistics.median(upms) if upms else 100

PREMIUM_TH = {'Krabi','Krabi/Andaman','Phuket','Phang Nga','Koh Samui (Surat Thani)',
              'Koh Samui','Koh Phangan','Koh Lanta','Rayong','Trang','Surat Thani',
              'Chumphon','Ranong','Petchaburi','Prachuap Khiri Khan','Chanthaburi','Trat'}

rows = []
for r in raw:
    sqm = r.get("sqm") or 0
    if sqm < 200: continue
    usd = r.get("price_usd") or 0
    if usd < 5000: continue
    ac = round(sqm / 4046.86, 3)
    upm = round(usd / sqm, 1)

    rb = ["src:propertyhub-th"]
    score = 16; rb.append("acc+16")
    b = sb(ac); score += b; rb.append(f"size{'+' if b>=0 else ''}{b}")

    if med_upm and upm:
        ratio = upm / med_upm
        if ratio < 0.4: vb = 10
        elif ratio < 0.7: vb = 6
        elif ratio < 1.0: vb = 3
        elif ratio < 1.5: vb = 0
        elif ratio < 2.5: vb = -3
        else: vb = -6
        if vb: score += vb; rb.append(f"val{'+' if vb>0 else ''}{vb}")

    lat, lng = r["lat"], r["lng"]
    coast_km = round(min(hav(lat, lng, a, b) for a,b in COAST), 2)
    if coast_km <= 0.5: score += 18; rb.append("beachfront+18")
    elif coast_km <= 2: score += 12; rb.append("coast≤2km+12")
    elif coast_km <= 10: score += 6; rb.append("coast≤10km+6")

    vp_hits = []
    for name, vlat, vlng in VP:
        d = round(hav(lat, lng, vlat, vlng), 2)
        if d <= 3: score += 25; rb.append("vp≤3km+25"); vp_hits.append({"name":name,"km":d})
        elif d <= 10: score += 18; rb.append("vp≤10km+18"); vp_hits.append({"name":name,"km":d})
        elif d <= 25: score += 10; rb.append("vp≤25km+10"); vp_hits.append({"name":name,"km":d})
        elif d <= 40: score += 5; rb.append("vp≤40km+5"); vp_hits.append({"name":name,"km":d})

    dist_bonus = r.get("distress_bonus") or 0
    if dist_bonus > 0:
        score += dist_bonus
        rb.append(f"forced-sale+{dist_bonus}")

    # Thai foreign friction (same as FazWaz merge: -5)
    score -= 5; rb.append("foreign_th_land-5")
    if r["province"] in PREMIUM_TH:
        score += 10; rb.append("th-premium-beach+10")

    rows.append({
        "tp": "land", "cf": "Thailand",
        "r": round(score, 1),
        "rg": r["province"],
        "a": "",
        "ac": ac, "m2": int(sqm), "usd": usd, "upm": upm,
        "v": "beachfront" if coast_km and coast_km <= 0.5 else "sea_visible" if coast_km and coast_km <= 2 else "",
        "el": "",
        "t": "Chanote (Thai) — verify with seller",
        "lat": lat, "lon": lng,
        "cur": "THB", "lp": str(r.get("price_thb",0)),
        "rb": "+".join(rb),
        "img": r.get("img") or "",
        "imgs": [r["img"]] if r.get("img") else [],
        "u": r["url"],
        "apt": "", "apt_km": None,
        "name": r.get("title","")[:200],
        "ski_km": None, "coast_km": coast_km,
        "viewpoints": vp_hits or None,
        "distress": min(100, dist_bonus + 5) if dist_bonus else None,
        "distress_keywords": r.get("distress_hits") or None,
        "foreign_friction": -5,
        "foreign_note": "Thai land: freehold blocked for foreigners, Thai-company structure is standard workaround.",
        "source_platform": "propertyhub.in.th",
        "rai_display": r.get("rai_display",""),
    })

existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing = [e for e in existing if "src:propertyhub-th" not in (e.get("rb","") or "")]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda r: r.get("r",0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json","w"))
print(f"merged: {len(rows)} new PropertyHub rows; total {len(merged)}", file=sys.stderr)

by_prov = Counter(r["rg"] for r in rows)
print(f"by province: {by_prov.most_common()}", file=sys.stderr)
n_dist = sum(1 for r in rows if r.get("distress"))
print(f"distressed: {n_dist}", file=sys.stderr)
