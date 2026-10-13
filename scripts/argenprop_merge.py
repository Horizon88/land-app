"""Merge Argenprop (Argentine mountain land + Patagonia campos) into listings.json.

Foreign ownership (Ley 26.737, 2011): foreigners CAN hold title, but rural
land is capped — 15% of any district foreign-held in aggregate, 1,000 ha max
per foreign person in core zones — and anything in the border security zone
(zona de seguridad de fronteras: most of Andean Patagonia incl. Bariloche)
needs prior federal clearance (DNM/Interior). Urban lots exempt. Scored -10:
real friction, but freehold — unlike the Thai nominee mess.

Currency: idmoneda=2 is USD on Argenprop; anything else without explicit
USD text is skipped (ARS asks are stale-inflation noise).
"""
import json, math, statistics, sys
from collections import Counter
from html import unescape

raw = json.load(open("/tmp/argenprop.json"))
print(f"raw Argenprop: {len(raw)}", file=sys.stderr)

SKI = [(r["name"], r["lat"], r["lon"]) for r in json.load(open("/home/user/land-app/scripts/ski_resorts.json"))
       if r["region"] == "AR"]

SIZE_TIERS = [(0.1,-25),(0.25,-12),(0.5,0),(1,6),(2.5,14),(5,22),(10,32),(25,44),(50,56),(100,68),(500,80),(float("inf"),92)]
def sb(ac):
    for t,b in SIZE_TIERS:
        if ac < t: return b
    return 92

def hav(a,b,c,d):
    R=6371
    dl=math.radians(c-a); dlo=math.radians(d-b)
    h=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

upms = [r["monto"]/r["m2"] for r in raw
        if r.get("monto") and r.get("m2") and r["moneda"] == "2"]
med_upm = statistics.median(upms) if upms else 50

rows = []
for r in raw:
    if r.get("moneda") != "2" and not r.get("usd_text"):
        continue
    usd = r.get("monto") or 0
    m2 = r.get("m2") or 0
    if usd < 5000 or m2 < 100:
        continue
    ac = round(m2 / 4046.86, 3)
    raw_upm = usd / m2
    upm = round(raw_upm, 3 if raw_upm < 1 else (2 if raw_upm < 10 else 1))

    rb = ["src:argenprop"]
    score = 16; rb.append("acc+16")
    b = sb(ac); score += b; rb.append(f"size{'+' if b>=0 else ''}{b}")

    ratio = upm / med_upm if med_upm else 1
    if ratio < 0.4: vb = 10
    elif ratio < 0.7: vb = 6
    elif ratio < 1.0: vb = 3
    elif ratio < 1.5: vb = 0
    elif ratio < 2.5: vb = -3
    else: vb = -6
    if vb: score += vb; rb.append(f"val{'+' if vb>0 else ''}{vb}")

    lat, lng = r["lat"], r["lng"]
    ski_km, ski_r = min(((hav(lat, lng, la, lo), n) for n, la, lo in SKI))
    ski_km = round(ski_km, 2)
    if ski_km <= 2: score += 15; rb.append("ski≤2km+15")
    elif ski_km <= 10: score += 10; rb.append("ski≤10km+10")
    elif ski_km <= 30: score += 5; rb.append("ski≤30km+5")
    if ac >= 5 and ski_km <= 40: score += 8; rb.append("sled+8")

    score -= 10; rb.append("foreign_ar_rural-10")

    title = unescape(r.get("title") or "").strip()
    rows.append({
        "tp": "land", "cf": "Argentina",
        "r": round(score, 1),
        "rg": r["region"].replace(" (campo)", ""),
        "a": unescape(r.get("loc_text") or "").split(",")[0][:40],
        "ac": ac, "m2": int(m2), "usd": usd, "upm": upm,
        "v": "mountain",
        "el": "",
        "t": "Freehold (Ley 26.737: rural caps + border-zone clearance for foreigners)",
        "lat": lat, "lon": lng,
        "cur": "USD", "lp": str(usd),
        "rb": "+".join(rb),
        "imgs": [r["img"]] if r.get("img") else [],
        "u": f"https://www.argenprop.com{r['path']}",
        "apt": "", "apt_km": None,
        "name": title[:180] or f"{r['region']} — {round(ac,1)} ac",
        "ski_km": ski_km, "ski_r": ski_r,
        "coast_km": None,
        "foreign_friction": -10,
        "geocode_src": "city",
        "alpine": True,
    })

existing = json.load(open("/home/user/land-app/docs/listings.json"))
existing = [e for e in existing if "src:argenprop" not in (e.get("rb", "") or "")]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda x: x.get("r", 0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json", "w"), separators=(",", ":"))
print(f"merged: {len(rows)} new Argentina rows; total {len(merged)}", file=sys.stderr)
print("by region:", Counter(r["rg"] for r in rows).most_common(), file=sys.stderr)
