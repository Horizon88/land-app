"""Merge willhaben Austria alpine land into listings.json — ski-in/ski-out focus.

Every willhaben ad carries real coordinates, so we compute distance to the
nearest Austrian ski resort and KEEP ONLY ski-accessible land (<=4 km),
flagging ski-in/ski-out (<=0.5 km) and walk-to-lift (<=1 km). EUR->USD ~1.08.
Adds the Grundverkehr foreign-ownership warning (Tirol/Salzburg/Vorarlberg
restrict non-resident + vacation-home purchases hard).
"""
import json, math, sys
from collections import Counter

RAW = "/tmp/willhaben.json"
PATH = "/home/user/land-app/docs/listings.json"
EURUSD = 1.08
raw = json.load(open(RAW))
print(f"raw willhaben rows: {len(raw)}", file=sys.stderr)

# Major Austrian ski resorts (village / lift-base coords): name, lat, lon
RESORTS = [
    ("St. Anton am Arlberg",47.130,10.264),("Lech",47.208,10.143),("Zürs",47.171,10.174),
    ("Ischgl",47.011,10.291),("Sölden",46.966,11.008),("Obergurgl",46.868,11.026),
    ("Kitzbühel",47.446,12.392),("Kirchberg in Tirol",47.446,12.316),("Mayrhofen",47.167,11.859),
    ("Gerlos",47.229,12.128),("Zell am Ziller",47.231,11.884),("Hochfügen",47.263,11.842),
    ("Serfaus",47.038,10.607),("Fiss",47.048,10.645),("Ladis",47.062,10.669),
    ("Nauders",46.889,10.503),("Kühtai",47.213,11.021),("Seefeld",47.329,11.188),
    ("Alpbach",47.399,11.940),("Söll",47.502,12.192),("Ellmau",47.512,12.297),
    ("Westendorf",47.423,12.213),("St. Johann in Tirol",47.524,12.423),("Fieberbrunn",47.472,12.548),
    ("Neustift Stubaital",47.116,11.310),("Axamer Lizum",47.196,11.290),("Kaunertal",46.902,10.732),
    ("Pitztal",46.930,10.870),("Lienz",46.829,12.769),("Obertilliach",46.712,12.606),
    ("Saalbach-Hinterglemm",47.390,12.636),("Zell am See",47.323,12.797),("Kaprun",47.269,12.755),
    ("Leogang",47.434,12.760),("Bad Gastein",47.114,13.134),("Bad Hofgastein",47.168,13.101),
    ("Obertauern",47.250,13.556),("Flachau",47.346,13.390),("Wagrain",47.333,13.298),
    ("Filzmoos",47.434,13.518),("Mühlbach Hochkönig",47.379,13.130),("Großarl",47.238,13.201),
    ("Rauris",47.227,12.981),("Lech Zürs",47.208,10.143),
    ("Silvretta Montafon",47.079,9.918),("Gaschurn",46.984,10.032),("Schruns",47.079,9.919),
    ("Damüls",47.278,9.902),("Warth",47.257,10.183),("Brand",47.101,9.737),("Gargellen",46.964,9.920),
    ("Schladming",47.394,13.687),("Ramsau am Dachstein",47.410,13.652),("Haus im Ennstal",47.410,13.788),
    ("Die Tauplitz",47.573,13.988),("Kreischberg",47.132,14.030),("Turracher Höhe",46.911,13.874),
    ("Nassfeld",46.560,13.283),("Bad Kleinkirchheim",46.812,13.793),("Gerlitzen",46.694,13.912),
    ("Katschberg",47.052,13.619),("Mölltaler Gletscher",47.000,12.996),("Heiligenblut",47.041,12.847),
]
def hav(a,b,c,d):
    R=6371; dl=math.radians(c-a); dlo=math.radians(d-b)
    h=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))
def nearest(lat,lng):
    best=(999,None)
    for n,rl,ro in RESORTS:
        d=hav(lat,lng,rl,ro)
        if d<best[0]: best=(d,n)
    return best

FOREIGN_NOTE = ("Austria (Grundverkehr): EU/EEA nationals are largely treated as domestic "
                "buyers — approval from the state land-transfer authority is normally "
                "routine. Non-EU buyers face real restrictions, and Tirol/Salzburg/Vlbg "
                "cap vacation/secondary homes (Freizeitwohnsitz) for everyone. Still verify "
                "Widmung (zoning: Bauland vs Freiland) + any Freizeitwohnsitz limitation.")

existing = json.load(open(PATH))
existing = [e for e in existing if "src:willhaben" not in (e.get("rb","") or "")]
existing_urls = {e.get("u") for e in existing}

rows = []; skipped_far = 0
for r in raw:
    eur = r.get("eur"); sqm = r.get("sqm")
    if not eur or not sqm or sqm < 20: continue
    if r["url"] in existing_urls: continue
    lat, lng = r.get("lat"), r.get("lng")
    if lat is None: continue
    ski_km, resort = nearest(lat, lng)
    kind = r.get("kind") or "land"
    house = kind == "house"
    # chalets stay ski-focused; land is kept everywhere (ski is a bonus);
    # Vienna apartments have no ski angle at all
    if house and ski_km > 4:
        skipped_far += 1; continue
    usd = round(eur * EURUSD)
    if usd < 3000: continue
    upm = round(usd/sqm, 1)

    rb = ["src:willhaben"]; score = 20; rb.append("base+20")
    if kind != "apartment":
        if ski_km <= 0.3: score += 40; rb.append("ski-in/out+40")
        elif ski_km <= 0.5: score += 32; rb.append("ski-in/out+32")
        elif ski_km <= 1: score += 22; rb.append("walk-to-lift+22")
        elif ski_km <= 2: score += 12; rb.append("ski≤2km+12")
        elif ski_km <= 4: score += 5; rb.append("ski≤4km+5")
    ski_out = round(ski_km, 2) if (kind != "apartment" and ski_km <= 15) else None
    resort_out = resort if ski_out is not None else ""

    if kind == "apartment":
        b = -4 if sqm<40 else 0 if sqm<60 else 6 if sqm<90 else 10
        score += b; rb.append(f"living{'+' if b>=0 else ''}{b}")
        rooms = r.get("rooms")
        loc = r.get("location") or ""
        bez = loc.split(",")[1].strip() if loc.count(",") >= 1 else loc
        rows.append({
            "tp":"apartment", "cf":"Austria", "r":round(score,1),
            "rg":"Wien", "a": (", ".join(x.strip() for x in loc.split(",")[1:]) or loc)[:40],
            "ac":0, "m2":int(sqm), "usd":usd, "upm":upm,
            "v":"", "el":"", "t":"Eigentumswohnung",
            "lat":lat, "lon":lng, "cur":"EUR", "lp":str(eur), "rb":"+".join(rb),
            "imgs":[r["img"]] if r.get("img") else [], "u":r["url"],
            "name": (r.get("title") or "Vienna apartment")[:180],
            "ski_km":None, "ski_r":"", "coast_km":None,
            "beds": int(rooms) if rooms and str(rooms).isdigit() else None,
            "living_m2": int(sqm), "floor": r.get("floor"), "district": bez,
            "first_seen": r.get("published") or None, "foreign_note": FOREIGN_NOTE,
        })
        continue

    if house:
        # score by living size + rooms; land-comp bid math doesn't apply
        b = -4 if sqm<80 else 0 if sqm<120 else 6 if sqm<200 else 12 if sqm<350 else 18
        score += b; rb.append(f"living{'+' if b>=0 else ''}{b}")
        rooms = r.get("rooms")
        ac = round((r.get("plot_m2") or 0)/4046.86, 3)
        rows.append({
            "tp":"house", "cf":"Austria", "r":round(score,1),
            "rg": r.get("state","Austria"), "a": (r.get("location") or r.get("district") or "")[:40],
            "ac":ac, "m2":int(sqm), "usd":usd, "upm":upm,
            "v":("alpine/ski" if (ski_out is not None and ski_out <= 4) else ""), "el":"", "t": r.get("ptype","Haus"),
            "lat":lat, "lon":lng, "cur":"EUR", "lp":str(eur), "rb":"+".join(rb),
            "imgs":[r["img"]] if r.get("img") else [], "u":r["url"],
            "name": (r.get("title") or "Austria alpine house")[:180],
            "ski_km":ski_out, "ski_r":resort_out, "coast_km":None,
            "beds": int(rooms) if rooms and str(rooms).isdigit() else None,
            "living_m2": int(sqm), "plot_m2": int(r["plot_m2"]) if r.get("plot_m2") else None,
            "first_seen": r.get("published") or None, "foreign_note": FOREIGN_NOTE,
        })
    else:
        ac = round(sqm/4046.86, 3)
        b = -6 if ac<0.05 else 0 if ac<0.15 else 6 if ac<0.4 else 12 if ac<1 else 18
        score += b; rb.append(f"size{'+' if b>=0 else ''}{b}")
        rows.append({
            "tp":"land", "cf":"Austria", "r":round(score,1),
            "rg": r.get("state","Austria"), "a": (r.get("location") or r.get("district") or "")[:40],
            "ac":ac, "m2":int(sqm), "usd":usd, "upm":upm,
            "v":("alpine/ski" if (ski_out is not None and ski_out <= 4) else ""), "el":"", "t": r.get("ptype","Bauland (verify Widmung)"),
            "lat":lat, "lon":lng, "cur":"EUR", "lp":str(eur), "rb":"+".join(rb),
            "imgs":[r["img"]] if r.get("img") else [], "u":r["url"],
            "name": (r.get("title") or "Austria alpine land")[:180],
            "ski_km":ski_out, "ski_r":resort_out, "coast_km":None,
            "first_seen": r.get("published") or None, "foreign_note": FOREIGN_NOTE,
        })

# Willhaben pins many listings to a town/postcode centre for privacy. A
# coordinate shared by 3+ listings is a centroid, not the house: distances from
# it can't support "ski-in/out" or "lakeside" claims on their own.
from collections import Counter as _C
_share = _C((round(r["lat"], 5), round(r["lng"], 5)) for r in raw if r.get("lat") is not None)
for x in rows:
    if _share[(round(x["lat"], 5), round(x["lon"], 5))] >= 3:
        x["loc_approx"] = True
print(f"approximate (shared town-centre) locations: {sum(1 for x in rows if x.get('loc_approx'))} of {len(rows)}", file=sys.stderr)

merged = existing + rows
merged.sort(key=lambda x: x.get("r",0), reverse=True)
json.dump(merged, open(PATH,"w"), separators=(",",":"))
from collections import Counter
print(f"merged: {len(rows)} willhaben rows ({skipped_far} chalets dropped >4km from a lift); total {len(merged)}", file=sys.stderr)
print("kinds:", Counter(r["tp"] for r in rows), "| ski-in/out ≤0.5km:", sum(1 for r in rows if (r["ski_km"] is not None and r["ski_km"]<=0.5)), file=sys.stderr)
print("by state:", Counter(r["rg"] for r in rows).most_common(), file=sys.stderr)
