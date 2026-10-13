"""Merge realtor.com/international land into listings.json (country-aware).

Per-country config supplies a coarse coastline (for a coast-distance bonus)
and the foreign-ownership note. Region = parish (Grenada) or state (Brazil)
parsed from the address.
"""
import json, math, re, statistics, sys
from collections import Counter

RAW = "/tmp/realtor_intl.json"
PATH = "/home/user/land-app/docs/listings.json"

def hav(a,b,c,d):
    R=6371; dl=math.radians(c-a); dlo=math.radians(d-b)
    h=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

# ── per-country config ────────────────────────────────────────────────
GRENADA_COAST = [
    (12.007,-61.786),(12.050,-61.770),(12.120,-61.768),(12.190,-61.740),
    (12.223,-61.690),(12.210,-61.615),(12.160,-61.600),(12.100,-61.610),
    (12.030,-61.650),(11.995,-61.700),(11.985,-61.758),(12.007,-61.786),
]
# coarse Brazilian Atlantic coast anchors (NE + SE, where the listings cluster)
BRAZIL_COAST = [
    (-2.90,-40.05),(-3.72,-38.52),(-4.55,-37.77),(-5.20,-35.46),(-5.80,-35.21),
    (-6.97,-34.83),(-7.12,-34.80),(-8.05,-34.87),(-9.66,-35.71),(-10.95,-37.05),
    (-12.97,-38.51),(-13.00,-38.53),(-15.83,-38.95),(-16.45,-39.07),(-18.35,-39.73),
    (-20.32,-40.29),(-22.97,-43.18),(-23.50,-45.10),(-25.43,-48.50),(-27.60,-48.55),
]
COUNTRY = {
    "Grenada": {
        "coast": GRENADA_COAST,
        "region": lambda a: ("St. " + re.search(r'\b(?:St\.?|Saint)\s+([A-Za-z]+)', a).group(1).capitalize())
                    if re.search(r'\b(?:St\.?|Saint)\s+([A-Za-z]+)', a or "") else "Grenada",
        "note": ("Grenada: non-nationals need an Alien Landholding Licence (ALHL) — "
                 "budget ~10% of price + legal; also a Citizenship-by-Investment route."),
        "title": "freehold (ALHL for foreigners)",
    },
    "Brazil": {
        "coast": BRAZIL_COAST,
        # Brazilian address tail is usually "..., <State> <CEP>"; grab the state word
        "region": lambda a: (re.search(r',\s*([A-Za-zçãáéíóú ]+?)(?:\s+\d{5}-?\d{3})?\s*$', a).group(1).strip()
                     if a and re.search(r',\s*([A-Za-zçãáéíóú ]+?)(?:\s+\d{5}-?\d{3})?\s*$', a) else "Brazil"),
        "note": ("Brazil: foreigners may own urban and most titled land freely; but "
                 "RURAL land is capped/needs INCRA approval for larger areas, and land "
                 "within 150 km of a land border (faixa de fronteira) needs national-"
                 "security clearance. Verify título + georreferenciamento."),
        "title": "titled (verify)",
    },
}

def sea_view(addr):
    return bool(re.search(r'beach|anse|epines|bay|point|sea|ocean|calivigny|sauteurs|'
                          r'praia|canoa|pipa|jeri|trancoso|litoral|costa', addr or "", re.I))

raw = json.load(open(RAW))
print(f"raw realtor-intl rows: {len(raw)}", file=sys.stderr)

existing = json.load(open(PATH))
existing = [e for e in existing if "src:realtor-intl" not in (e.get("rb","") or "")]
existing_urls = {e.get("u") for e in existing}

upms = [r["usd"]/(r["sqft"]*0.092903) for r in raw if r.get("usd") and r.get("sqft")]
med = statistics.median(upms) if upms else 100

rows = []
for r in raw:
    usd = r.get("usd"); sqft = r.get("sqft")
    if not usd or not sqft or sqft < 400: continue
    if r["url"] in existing_urls: continue
    name = r.get("country")
    cfg = COUNTRY.get(name)
    if not cfg: continue
    sqm = sqft * 0.092903
    ac = round(sqft/43560, 3)
    upm = round(usd/sqm, 1)
    lat, lng = r["lat"], r["lng"]
    coast_km = round(min(hav(lat,lng,a,b) for a,b in cfg["coast"]), 2)

    rb = ["src:realtor-intl"]; score = 18; rb.append("base+18")
    b = -8 if ac<0.25 else 0 if ac<0.5 else 8 if ac<1 else 16 if ac<3 else 26 if ac<10 else 34
    score += b; rb.append(f"size{'+' if b>=0 else ''}{b}")
    ratio = upm/med if med else 1
    vb = 12 if ratio<0.5 else 7 if ratio<0.8 else 3 if ratio<1.0 else 0 if ratio<1.5 else -4 if ratio<2.5 else -8
    if vb: score += vb; rb.append(f"val{'+' if vb>0 else ''}{vb}")
    if coast_km <= 0.5: score += 20; rb.append("beachfront+20")
    elif coast_km <= 2: score += 14; rb.append("coast≤2km+14")
    elif coast_km <= 8: score += 8; rb.append("coast≤8km+8")

    rows.append({
        "tp":"land", "cf":name, "r":round(score,1),
        "rg": cfg["region"](r.get("addr")), "a": (r.get("addr") or "")[:40],
        "ac":ac, "m2":int(sqm), "usd":usd, "upm":upm,
        "v":"sea_view" if sea_view(r.get("addr")) else "coastal",
        "el":"", "t":cfg["title"], "lat":lat, "lon":lng,
        "cur":"USD", "lp":str(usd), "rb":"+".join(rb),
        "imgs":[], "u":r["url"], "name": (r.get("addr") or (name+" land"))[:180],
        "ski_km":None, "ski_r":"", "coast_km":coast_km,
        "foreign_note": cfg["note"],
    })

merged = existing + rows
merged.sort(key=lambda x: x.get("r",0), reverse=True)
json.dump(merged, open(PATH,"w"), separators=(",",":"))
print(f"merged: {len(rows)} realtor-intl rows; total {len(merged)}", file=sys.stderr)
print("by country/region:", Counter((r["cf"],r["rg"]) for r in rows).most_common(), file=sys.stderr)
