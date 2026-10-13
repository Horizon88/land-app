"""Merge chavesnamao Brazil land into listings.json (coastal lots + farmland).

Additive by URL: re-running one region updates its rows without wiping the
other regions' chavesnamao rows. Scores by kind — 'terreno' (coastal SC lots)
gets coastal proximity + premium-beach bonuses; 'fazenda' (Bahia farmland)
gets agricultural size/value scoring and the strong rural foreign-ownership
restriction note.
"""
import json, math, re, statistics, sys
from collections import Counter

RAW = "/tmp/chavesnamao.json"
PATH = "/home/user/land-app/docs/listings.json"
BRLUSD = 1 / 5.4
raw = json.load(open(RAW))
print(f"raw chavesnamao rows: {len(raw)}", file=sys.stderr)

SC_COAST = [
    (-26.24,-48.64),(-26.90,-48.62),(-27.10,-48.55),(-27.28,-48.36),(-27.44,-48.40),
    (-27.60,-48.45),(-27.78,-48.50),(-27.99,-48.62),(-28.24,-48.65),(-28.50,-48.78),
    (-28.68,-48.99),(-26.78,-48.55),(-27.16,-48.50),
]
def hav(a,b,c,d):
    R=6371; dl=math.radians(c-a); dlo=math.radians(d-b)
    h=math.sin(dl/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlo/2)**2
    return 2*R*math.asin(math.sqrt(h))

NOTE_COAST = ("Brazil: foreigners may own urban/titled land freely; verify título + "
              "georreferenciamento. Rural land has extra limits (see farmland notes).")
NOTE_FARM = ("Brazil RURAL land: foreign ownership is CAPPED by Law 5.709/71 — a foreign "
             "person/foreign-controlled company may hold only a limited number of rural "
             "'modules', and larger areas need INCRA + (for big tracts) National Congress "
             "approval. Structure via a Brazilian entity with counsel. Verify título, "
             "georreferenciamento (SIGEF), CAR, and água/outorga.")
PREMIUM = re.compile(r'jurere|campeche|praia|jardim|ponta|lagoa|santinho|ingleses|'
                     r'canasvieiras|rosa|mole|joaquina|brava|estaleiro', re.I)

existing = json.load(open(PATH))
raw_urls = {r["url"] for r in raw}
# additive: drop only the rows we're about to re-add (same URLs); keep other regions
existing = [e for e in existing if e.get("u") not in raw_urls]
existing_urls = {e.get("u") for e in existing}

def build(r):
    brl = r.get("price_rm"); sqm = r.get("sqm")
    if not brl or not sqm or sqm < 100: return None
    if r.get("lat") is None: return None
    if r["url"] in existing_urls: return None
    usd = round(brl * BRLUSD)
    if usd < 5000: return None
    ac = round(sqm/4046.86, 3); ha = sqm/10000
    upm = round(usd/sqm, 2 if usd/sqm < 100 else 1)
    lat, lng = r["lat"], r["lng"]
    farm = r.get("kind") == "fazenda"
    if farm:
        uph_chk = usd / (sqm / 10000) if sqm else 0
        # western-Bahia farmland tops out ~$20-30k/ha; >$80k/ha is a seller
        # data-entry error (wrong unit or an extra price digit) — drop it.
        if uph_chk > 80000:
            return None

    rb = ["src:chavesnamao"]; score = 18; rb.append("base+18")
    if farm:
        # agricultural: reward scale; value per hectare
        uph = usd/ha if ha else 0
        b = -6 if ha<5 else 4 if ha<50 else 12 if ha<200 else 20 if ha<1000 else 28
        score += b; rb.append(f"scale{'+' if b>=0 else ''}{b}")
        vb = 10 if uph<1500 else 6 if uph<4000 else 2 if uph<9000 else -3 if uph<20000 else -8
        score += vb; rb.append(f"val{'+' if vb>0 else ''}{vb}")
        coast_km = None; v = ""
        rg = f"{r.get('city','')} (BA farm)"
        name = f"Fazenda {round(ha):,} ha · {r.get('city','')}, Bahia"
        note = NOTE_FARM; title = "rural (foreign cap — Law 5.709/71)"
    else:
        coast_km = round(min(hav(lat,lng,a,b) for a,b in SC_COAST), 1)
        b = -10 if ac<0.1 else -4 if ac<0.25 else 2 if ac<0.6 else 10 if ac<1.5 else 18 if ac<5 else 26
        score += b; rb.append(f"size{'+' if b>=0 else ''}{b}")
        med = 100
        ratio = upm/med
        vb = 12 if ratio<0.5 else 7 if ratio<0.8 else 3 if ratio<1.0 else 0 if ratio<1.5 else -4 if ratio<2.5 else -8
        if vb: score += vb; rb.append(f"val{'+' if vb>0 else ''}{vb}")
        if coast_km <= 1: score += 18; rb.append("coast≤1km+18")
        elif coast_km <= 3: score += 11; rb.append("coast≤3km+11")
        elif coast_km <= 8: score += 5; rb.append("coast≤8km+5")
        nb = r.get("neighborhood","")
        prem = bool(PREMIUM.search(nb + " " + r.get("city","")))
        if prem: score += 6; rb.append("premium-beach+6")
        v = "sea_view" if prem or coast_km<=1 else "coastal"
        rg = r.get("city","Santa Catarina")
        name = f"Terreno {int(sqm)}m² · {nb}, {r.get('city','')} (SC)"
        note = NOTE_COAST; title = "titled (verify)"

    return {
        "tp":"land", "cf":"Brazil", "r":round(score,1),
        "rg": rg, "a": (r.get("neighborhood") or "")[:40],
        "ac":ac, "m2":int(sqm), "usd":usd, "upm":upm,
        "v":v, "el":"", "t":title, "lat":lat, "lon":lng,
        "cur":"BRL", "lp":str(brl), "rb":"+".join(rb),
        "imgs":[], "u":r["url"], "name": name[:180],
        "ski_km":None, "ski_r":"", "coast_km":coast_km,
        "foreign_note": note,
    }

rows = [x for x in (build(r) for r in raw) if x]
merged = existing + rows
merged.sort(key=lambda x: x.get("r",0), reverse=True)
json.dump(merged, open(PATH,"w"), separators=(",",":"))
print(f"merged: {len(rows)} chavesnamao rows; total {len(merged)}", file=sys.stderr)
print("by region:", Counter(r["rg"] for r in rows).most_common(12), file=sys.stderr)
