"""Merge Redfin South Coast MA land + homes into listings.json.

Land → tp:'land' scored on size, $/acre value and coast proximity.
Homes → tp:'house' scored on coast proximity, $/sqft value vs the local
median, living size and staleness; carries beds/baths/living area/lot/year.
All rows get rg='Massachusetts' so the app's Massachusetts tab can scope them.
"""
import json, math, statistics, sys
from collections import Counter

RAW = "/tmp/redfin_ma.json"
PATH = "/home/user/land-app/docs/listings.json"
raw = json.load(open(RAW))
print(f"raw redfin-ma rows: {len(raw)}", file=sys.stderr)

# South Coast MA coastline anchors (Buzzards Bay + Mount Hope Bay + Sakonnet)
COAST = [
    (41.509,-71.088),(41.545,-71.045),(41.575,-70.985),(41.590,-70.940),
    (41.628,-70.918),(41.638,-70.882),(41.660,-70.818),(41.700,-70.762),
    (41.745,-70.718),(41.704,-71.155),(41.600,-71.200),(41.520,-71.100),
    (41.552,-70.876),(41.665,-70.930),(41.735,-71.185),(41.760,-70.745),
]
def hav(a,b,c,d):
    R=6371; dl=math.radians(c-a); dlo=math.radians(d-b)
    h=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

existing = json.load(open(PATH))
existing = [e for e in existing if "src:redfin-ma" not in (e.get("rb","") or "")]
existing_urls = {e.get("u") for e in existing}

land = [r for r in raw if r.get("kind") == "land"]
homes = [r for r in raw if r.get("kind") == "house"]
upas = sorted(r["price_usd"]/r["acres"] for r in land if r.get("acres") and r["acres"] >= 0.1)
med_upa = statistics.median(upas) if upas else 100000
ppsf = sorted(r["price_usd"]/r["sqft_living"] for r in homes if r.get("sqft_living") and r["sqft_living"] > 300)
med_ppsf = statistics.median(ppsf) if ppsf else 300

def coast_bonus(km, rb):
    if km <= 0.2: rb.append("waterfront+22"); return 22
    if km <= 1:   rb.append("coast≤1km+14"); return 14
    if km <= 3:   rb.append("coast≤3km+7");  return 7
    return 0

rows = []
for r in raw:
    usd = r.get("price_usd")
    if not usd or r["url"] in existing_urls: continue
    lat, lng = r["lat"], r["lng"]
    coast_km = round(min(hav(lat,lng,a,b) for a,b in COAST), 2)
    dom = r.get("dom")
    rb = ["src:redfin-ma"]; score = 22; rb.append("base+22")
    score += coast_bonus(coast_km, rb)
    if dom and dom >= 180: score += 6; rb.append("stale>6mo+6")
    v = "waterfront" if coast_km <= 0.2 else ("sea_visible" if coast_km <= 1.5 else "")
    base = {
        "cf":"USA", "rg":"Massachusetts", "a": (r.get("city") or "")[:40],
        "usd":usd, "v":v, "el":"", "lat":lat, "lon":lng,
        "cur":"USD", "lp":str(usd), "imgs":[], "u":r["url"],
        "ski_km":None, "ski_r":"", "coast_km":coast_km,
        "days_on_market": int(dom) if dom else None,
    }
    if r["kind"] == "land":
        ac = r.get("acres")
        if not ac or ac < 0.1: continue
        m2 = int(ac*4046.86)
        b = -8 if ac<0.25 else 0 if ac<0.5 else 8 if ac<1 else 16 if ac<3 else 24 if ac<10 else 32
        score += b; rb.append(f"size{'+' if b>=0 else ''}{b}")
        ratio = (usd/ac)/med_upa
        vb = 12 if ratio<0.4 else 7 if ratio<0.7 else 3 if ratio<1.0 else 0 if ratio<1.6 else -4 if ratio<2.6 else -8
        if vb: score += vb; rb.append(f"val{'+' if vb>0 else ''}{vb}")
        rows.append({**base, "tp":"land", "r":round(score,1), "ac":ac, "m2":m2,
                     "upm":round(usd/m2,1), "t":"",
                     "name": f"{r.get('address','')}, {r.get('city','')} MA".strip(", ")[:180],
                     "rb":"+".join(rb)})
    else:
        sqft = r.get("sqft_living")
        if not sqft or sqft < 300: continue
        if usd < 40000: continue          # sub-$40k "homes" are rents/typos, not sale prices
        living_m2 = int(sqft*0.092903)
        ratio = (usd/sqft)/med_ppsf
        vb = 12 if ratio<0.6 else 7 if ratio<0.8 else 3 if ratio<1.0 else 0 if ratio<1.3 else -4 if ratio<1.8 else -8
        if vb: score += vb; rb.append(f"val{'+' if vb>0 else ''}{vb}")
        b = -4 if sqft<900 else 0 if sqft<1500 else 5 if sqft<2500 else 9
        score += b; rb.append(f"living{'+' if b>=0 else ''}{b}")
        ac = r.get("acres") or 0
        if ac >= 1: score += 5; rb.append("lot≥1ac+5")
        beds = int(r["beds"]) if r.get("beds") else None
        baths = r.get("baths")
        rows.append({**base, "tp":"house", "r":round(score,1),
                     "ac":round(ac,3), "m2":living_m2, "upm":round(usd/living_m2,1),
                     "t": r.get("ptype",""),
                     "beds":beds, "baths":baths, "living_m2":living_m2,
                     "sqft_living":int(sqft), "plot_m2": int(ac*4046.86) if ac else None,
                     "year_built": int(r["year"]) if r.get("year") else None,
                     "hoa": int(r["hoa"]) if r.get("hoa") else None,
                     "usd_per_sqft": round(usd/sqft),
                     "name": f"{beds or '?'}bd {r.get('address','')}, {r.get('city','')} MA"[:180],
                     "rb":"+".join(rb)})

merged = existing + rows
merged.sort(key=lambda x: x.get("r",0), reverse=True)
json.dump(merged, open(PATH,"w"), separators=(",",":"))
print(f"merged: {len(rows)} redfin-ma rows {dict(Counter(r['tp'] for r in rows))}; total {len(merged)}", file=sys.stderr)
print(f"median home $/sqft: {round(med_ppsf)} · waterfront homes: {sum(1 for r in rows if r['tp']=='house' and r['coast_km']<=0.2)}", file=sys.stderr)
