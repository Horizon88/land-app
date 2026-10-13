"""Merge all-Japan SUUMO land / houses / Tokyo apartments into listings.json.

Rows replace any existing row with the same URL (e.g. older city-centroid
suumo-mtn rows) so they gain address-level coordinates; codes and archives
are keyed by URL, so they carry over unchanged.
"""
import json, math, re, statistics, sys
from collections import Counter

RAW = "/tmp/suumo_japan.json"
PATH = "/home/user/land-app/docs/listings.json"
JPYUSD = 0.0064
raw = [r for r in json.load(open(RAW)) if r.get("lat") is not None]
print(f"raw suumo-jp rows with coords: {len(raw)}", file=sys.stderr)

SKI = [(s["name"], s["lat"], s["lon"]) for s in json.load(open("/home/user/land-app/scripts/ski_resorts.json"))
       if 24 < s["lat"] < 46 and 122 < s["lon"] < 146]
def hav(a,b,c,d):
    R=6371; dl=math.radians(c-a); dlo=math.radians(d-b)
    h=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))
def nearest_ski(lat, lng):
    best = (999, "")
    for n, la, lo in SKI:
        if abs(la-lat) > 0.6 or abs(lo-lng) > 0.8: continue
        d = hav(lat, lng, la, lo)
        if d < best[0]: best = (d, n)
    return best

PREF_NAME = {"hokkaido_": "Hokkaido", "gumma": "Gunma"}
def pref_name(p): return PREF_NAME.get(p, p.replace("_", " ").title())
def beds(layout):
    if not layout: return None
    if "ワンルーム" in layout: return 1
    m = re.match(r"(\d+)", layout)
    return int(m.group(1)) if m else None

FOREIGN_NOTE = ("Japan: foreigners can buy land and property freehold with no residency "
                "requirement. Budget ~7-10% for acquisition tax, registration and agent fees; "
                "property tax ~1.4%/yr of the assessed value.")

existing = json.load(open(PATH))
raw_urls = {r["url"] for r in raw}
replaced = sum(1 for e in existing if e.get("u") in raw_urls)
existing = [e for e in existing if e.get("u") not in raw_urls]

rows = []
for r in raw:
    jpy = r["price_jpy"]; usd = round(jpy * JPYUSD)
    kind = r["kind"]; size = r["size_m2"]
    if not size or usd < 2000: continue
    lat, lng = r["lat"], r["lng"]
    ski_km, resort = nearest_ski(lat, lng)
    ski_km = round(ski_km, 2) if ski_km < 15 else None
    rb = [f"src:suumo-jp"]; score = 18; rb.append("base+18")
    if ski_km is not None:
        b = 30 if ski_km <= 0.5 else 22 if ski_km <= 1 else 12 if ski_km <= 3 else 5 if ski_km <= 8 else 0
        if b: score += b; rb.append(f"ski+{b}")
    if r.get("sea_hint"): score += 10; rb.append("sea-hint+10")
    w = r.get("walk_min")
    loc = r["city"].replace("_", " ").title()
    common = {
        "cf":"Japan", "rg": pref_name(r["pref"]), "a": loc[:40], "usd":usd,
        "v": "sea_view" if r.get("sea_hint") else ("mountain" if ski_km is not None and ski_km <= 8 else ""),
        "el":"", "lat":lat, "lon":lng, "cur":"JPY", "lp":str(jpy), "imgs":[], "u":r["url"],
        "ski_km": ski_km, "ski_r": resort if ski_km is not None else "", "coast_km":None,
        "station": r.get("station"), "walk_min": w, "year_built": r.get("year"),
        "foreign_note": FOREIGN_NOTE,
    }
    if kind == "land":
        ac = round(size/4046.86, 3)
        b = -6 if size<100 else 0 if size<300 else 6 if size<1000 else 12 if size<5000 else 18
        score += b; rb.append(f"size{'+' if b>=0 else ''}{b}")
        rows.append({**common, "tp":"land", "ac":ac, "m2":int(size), "upm":round(usd/size,1),
                     "t":"freehold", "r":round(score,1), "rb":"+".join(rb),
                     "name": f"{int(size)}m² land · {loc}, {pref_name(r['pref'])}"})
    elif kind == "house":
        plot = r.get("land_m2") or 0
        b = -4 if size<60 else 0 if size<90 else 5 if size<140 else 9
        score += b; rb.append(f"living{'+' if b>=0 else ''}{b}")
        if plot >= 500: score += 5; rb.append("plot≥500m²+5")
        rows.append({**common, "tp":"house", "ac":round(plot/4046.86,3), "m2":int(size),
                     "upm":round(usd/size,1), "t":"中古一戸建て (used house)",
                     "beds":beds(r.get("layout")), "layout":r.get("layout"),
                     "living_m2":int(size), "plot_m2":int(plot) if plot else None,
                     "r":round(score,1), "rb":"+".join(rb),
                     "name": f"{r.get('layout') or ''} house {int(size)}m² · {loc}, {pref_name(r['pref'])}".strip()})
    else:  # apartment
        if w is not None:
            b = 14 if w <= 3 else 10 if w <= 5 else 5 if w <= 8 else 0 if w <= 12 else -4
            score += b; rb.append(f"walk{w}min{'+' if b>=0 else ''}{b}")
        b = -4 if size<25 else 0 if size<40 else 5 if size<60 else 9
        score += b; rb.append(f"floor{'+' if b>=0 else ''}{b}")
        if (r.get("year") or 0) >= 2000: score += 4; rb.append("built≥2000+4")
        rows.append({**common, "tp":"apartment", "ac":0, "m2":int(size), "upm":round(usd/size,1),
                     "t":"区分所有 (apartment)", "beds":beds(r.get("layout")), "layout":r.get("layout"),
                     "living_m2":int(size), "r":round(score,1), "rb":"+".join(rb),
                     "name": (r.get("name") or f"{r.get('layout') or ''} apartment") + f" · {loc}"})

merged = existing + rows
merged.sort(key=lambda x: x.get("r",0), reverse=True)
json.dump(merged, open(PATH,"w"), separators=(",",":"))
print(f"merged: {len(rows)} suumo-jp rows {dict(Counter(r['tp'] for r in rows))} "
      f"({replaced} older rows upgraded); total {len(merged)}", file=sys.stderr)
print("Japan by prefecture (top):", Counter(r['rg'] for r in rows).most_common(10), file=sys.stderr)
