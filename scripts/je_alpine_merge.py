"""Merge JamesEdition Alpine (Switzerland / Austria / Georgia mountain homes)."""
import json, math, sys
from collections import Counter

raw = json.load(open("/tmp/je_alpine.json"))
print(f"raw JE alpine rows: {len(raw)}", file=sys.stderr)

# FX approximations to USD
FX = {"CHF": 1.12, "EUR": 1.08, "GEL": 0.37, "USD": 1.0, "": 1.08}

SIZE_TIERS = [(0.1,-25),(0.25,-12),(0.5,0),(1,6),(2.5,14),(5,22),(10,32),(25,44),(50,56),(100,68),(500,80),(float("inf"),92)]
def sb(ac):
    for t,b in SIZE_TIERS:
        if ac < t: return b
    return 92

# Alpine ski resorts curated for coord-based ski_km calc
SKI = [
    ('Verbier',46.10,7.23),('Zermatt',46.02,7.75),('St-Moritz',46.50,9.84),
    ('Gstaad',46.47,7.29),('Davos',46.80,9.83),('Crans-Montana',46.31,7.48),
    ('Villars',46.30,7.05),('Grindelwald',46.62,8.03),('Wengen',46.61,7.92),
    ('Andermatt',46.63,8.60),('Engelberg',46.82,8.40),('Laax',46.80,9.27),
    ('Kitzbühel',47.45,12.39),('Lech',47.21,10.14),('St-Anton',47.13,10.27),
    ('Sölden',46.97,11.00),('Ischgl',47.01,10.29),('Mayrhofen',47.17,11.87),
    ('Zell-am-See',47.33,12.79),('Bad-Gastein',47.11,13.13),('Saalbach',47.39,12.63),
    ('Serfaus',47.04,10.61),('Obertauern',47.25,13.55),
    ('Gudauri',42.47,44.48),('Bakuriani',41.75,43.53),('Kazbegi',42.66,44.64),
    ('Mestia',43.05,42.72),('Svaneti',42.92,42.73),('Goderdzi',41.61,42.51),
]
def hav(a,b,c,d):
    R=6371
    dl=math.radians(c-a); dlo=math.radians(d-b)
    h=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

rows = []
for r in raw:
    price_native = r.get("price_native") or 0
    if price_native < 10000: continue
    cur = r.get("currency") or ("CHF" if r["country"]=="Switzerland" else "EUR" if r["country"]=="Austria" else "USD")
    usd = round(price_native * FX.get(cur, 1.08))
    if usd < 20000: continue
    ac = r.get("acres") or 0.15   # default small mountain lot
    if ac < 0.05: ac = 0.15
    m2 = int(ac * 4046.86)
    upm = round(usd / m2, 1)
    lat = r.get("lat") or r.get("fb_lat")
    lng = r.get("lng") or r.get("fb_lng")

    rb = [f"src:je-alpine-{r['country'].lower()}"]
    score = 16; rb.append("acc+16")
    b = sb(ac); score += b; rb.append(f"size{'+' if b>=0 else ''}{b}")

    # Ski proximity
    ski_km = min(hav(lat, lng, la, lo) for _,la,lo in SKI)
    ski_r = min(SKI, key=lambda s: hav(lat, lng, s[1], s[2]))[0]
    if ski_km <= 0.5: score += 15; rb.append("ski-in+15")
    elif ski_km <= 2: score += 10; rb.append("ski≤2km+10")
    elif ski_km <= 10: score += 5; rb.append("ski≤10km+5")
    if ac >= 5 and ski_km <= 30: score += 8; rb.append("sled+8")

    ff = r["foreign_friction"]
    if ff: score += ff; rb.append(f"foreign_{r['country'].lower()[:2]}_alpine{'+' if ff>0 else ''}{ff}")

    rows.append({
        "tp":"land", "cf": r["country"],
        "r": round(score, 1),
        "rg": ski_r if ski_km <= 20 else r["country"],
        "a": r.get("loc","")[:40],
        "ac": round(ac,3), "m2": m2, "usd": usd, "upm": upm,
        "v": "mountain",
        "el": "",
        "t": "Chalet / mountain home (verify title)",
        "lat": lat, "lon": lng,
        "cur": cur, "lp": str(int(price_native)),
        "rb": "+".join(rb),
        "img": r.get("img","") or "",
        "imgs": [r["img"]] if r.get("img") else [],
        "u": r["url"],
        "apt":"","apt_km":None,
        "name": r.get("title","")[:180],
        "ski_km": round(ski_km,2), "ski_r": ski_r,
        "coast_km": None,
        "foreign_friction": r["foreign_friction"],
        "foreign_note": r["foreign_note"],
        "alpine": True,
    })

# Strip prior alpine rows for idempotency
existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing = [e for e in existing if "src:je-alpine" not in (e.get("rb","") or "")]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda r: r.get("r",0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json","w"))
print(f"merged: {len(rows)} new alpine rows; total {len(merged)}", file=sys.stderr)

by_cf = Counter(r["cf"] for r in rows)
print(f"by country: {by_cf.most_common()}", file=sys.stderr)
