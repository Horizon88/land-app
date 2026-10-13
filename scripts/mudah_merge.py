"""Merge mudah.my Malaysia land into listings.json.

Malaysia-specific: title type is the key signal for a foreign buyer —
Freehold (cleanly foreign-ownable above the state price floor) > Leasehold
(usually 99yr) > Malay Reserved (CANNOT be sold to non-Malays; flagged).
RM→USD at a fixed ~4.7. Coast distance from a coarse Malaysia outline.
"""
import json, math, re, statistics, sys
from collections import Counter

RAW = "/tmp/mudah.json"
PATH = "/home/user/land-app/docs/listings.json"
RMUSD = 1 / 4.7
raw = json.load(open(RAW))
print(f"raw mudah rows: {len(raw)}", file=sys.stderr)

# coarse Malaysia coastline anchors (W + E peninsula, Sabah, Sarawak)
COAST = [
    (6.44,100.19),(5.42,100.34),(4.85,100.73),(3.80,100.85),(2.80,101.40),
    (1.86,102.50),(1.48,103.63),(2.31,103.80),(3.80,103.34),(5.28,103.11),
    (6.13,102.29),(5.98,116.07),(4.24,114.02),(1.55,110.34),(2.02,111.85),
    (5.84,118.12),(4.40,113.99),
]
def hav(a,b,c,d):
    R=6371; dl=math.radians(c-a); dlo=math.radians(d-b)
    h=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

def title_info(t):
    s = (t or "").lower()
    if "malay reserv" in s: return ("Malay Reserved", -18, True)   # off-limits to foreigners
    if "freehold" in s:     return ("Freehold", 10, False)
    if "leasehold" in s:    return ("Leasehold", 0, False)
    if "bumi" in s:         return ("Bumi Lot", -12, True)
    return (t or "verify title", 0, False)

FOREIGN_NOTE = ("Malaysia: foreigners may own freehold land above a state price floor "
                "(commonly RM1M; RM2M in Penang island/Selangor/KL for some titles). "
                "Malay Reserved / Bumi lots CANNOT be sold to non-Malays. MM2H aids residency.")

def sea_view(txt):
    return bool(re.search(r'sea|beach|pantai|island|pulau|laut|coast|waterfront|langkawi', txt or "", re.I))

existing = json.load(open(PATH))
existing = [e for e in existing if "src:mudah" not in (e.get("rb","") or "")]
existing_urls = {e.get("u") for e in existing}

upms = [r["price_rm"]*RMUSD/r["sqm"] for r in raw if r.get("price_rm") and r.get("sqm") and r["sqm"]>=100]
med = statistics.median(upms) if upms else 30

rows = []
for r in raw:
    price_rm = r.get("price_rm"); sqm = r.get("sqm")
    if not price_rm or not sqm or sqm < 100: continue
    if r.get("lat") is None: continue
    if r["url"] in existing_urls: continue
    usd = round(price_rm * RMUSD)
    if usd < 3000: continue
    ac = round(sqm/4046.86, 3)
    upm = round(usd/sqm, 2 if usd/sqm < 100 else 1)
    lat, lng = r["lat"], r["lng"]
    coast_km = round(min(hav(lat,lng,a,b) for a,b in COAST), 1)

    rb = ["src:mudah"]; score = 16; rb.append("base+16")
    b = -10 if ac<0.15 else -4 if ac<0.4 else 2 if ac<1 else 10 if ac<3 else 18 if ac<10 else 26 if ac<50 else 34
    score += b; rb.append(f"size{'+' if b>=0 else ''}{b}")
    ratio = upm/med if med else 1
    vb = 12 if ratio<0.4 else 7 if ratio<0.7 else 3 if ratio<1.0 else 0 if ratio<1.5 else -4 if ratio<2.5 else -8
    if vb: score += vb; rb.append(f"val{'+' if vb>0 else ''}{vb}")
    tt, tb, restricted = title_info(r.get("title_type"))
    if tb: score += tb; rb.append(f"title{'+' if tb>0 else ''}{tb}")
    if coast_km <= 1: score += 16; rb.append("coast≤1km+16")
    elif coast_km <= 5: score += 9; rb.append("coast≤5km+9")
    elif coast_km <= 15: score += 4; rb.append("coast≤15km+4")

    txt = (r.get("title","") + " " + r.get("subarea","") + " " + r.get("region",""))
    rows.append({
        "tp":"land", "cf":"Malaysia", "r":round(score,1),
        "rg": r.get("region","Malaysia"), "a": (r.get("subarea") or "")[:40],
        "ac":ac, "m2":int(sqm), "usd":usd, "upm":upm,
        "v":"sea_view" if sea_view(txt) else "",
        "el":"", "t": tt, "lat":lat, "lon":lng,
        "cur":"MYR", "lp":str(price_rm), "rb":"+".join(rb),
        "imgs":[r["img"]] if r.get("img") else [], "u":r["url"],
        "name": (r.get("title") or "Malaysia land")[:180],
        "ski_km":None, "ski_r":"", "coast_km":coast_km,
        "first_seen": (r.get("date","")[:10] or None),
        "restricted_foreign": restricted or None,
        "foreign_note": FOREIGN_NOTE,
    })

merged = existing + rows
merged.sort(key=lambda x: x.get("r",0), reverse=True)
json.dump(merged, open(PATH,"w"), separators=(",",":"))
print(f"merged: {len(rows)} mudah rows; total {len(merged)}", file=sys.stderr)
print("by state:", Counter(r["rg"] for r in rows).most_common(12), file=sys.stderr)
print("by title:", Counter(r["t"] for r in rows).most_common(), file=sys.stderr)
