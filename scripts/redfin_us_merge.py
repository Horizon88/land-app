"""Merge Redfin US coast + ski regions (/tmp/redfin_us.json) into listings.json.

Land is scored on size and $/acre vs its region's median; homes on $/sqft vs the
region median, living size and lot. Then scripts/global_distances.py sets
coast_km / ski_km, and rows that are neither within 1.5 km of the sea nor 5 km
of a ski lift are moved to data/raw/redfin_us_rest.json.gz, so the app keeps
only oceanfront and ski-town properties.
"""
import gzip, json, os, statistics, subprocess, sys
from collections import Counter, defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RAW = "/tmp/redfin_us.json"
PATH = os.path.join(ROOT, "docs", "listings.json")
REST = os.path.join(ROOT, "data", "raw", "redfin_us_rest.json.gz")
SRC = "src:redfin-us"

def main():
    raw = json.load(open(RAW))
    existing = json.load(open(PATH))
    have = {e.get("u") for e in existing if SRC not in (e.get("rb") or "")}
    existing = [e for e in existing if SRC not in (e.get("rb") or "")]      # replace the previous US crawl
    upa, ppsf = defaultdict(list), defaultdict(list)
    for r in raw:
        if r["kind"] == "land" and r.get("acres") and r["acres"] >= 0.1: upa[r["region"]].append(r["price_usd"] / r["acres"])
        if r["kind"] == "house" and (r.get("sqft_living") or 0) > 300: ppsf[r["region"]].append(r["price_usd"] / r["sqft_living"])
    med_upa = {k: statistics.median(v) for k, v in upa.items() if v}
    med_ppsf = {k: statistics.median(v) for k, v in ppsf.items() if v}
    rows = []
    for r in raw:
        usd = r.get("price_usd"); reg = r["region"]
        if not usd or r["url"] in have: continue
        dom = r.get("dom"); rb = [SRC, f"region:{reg}"]; score = 22; rb.append("base+22")
        if dom and dom >= 180: score += 6; rb.append("stale>6mo+6")
        base = {"cf": "USA", "rg": reg, "a": (r.get("city") or "")[:40], "usd": usd, "v": "", "el": "",
                "lat": r["lat"], "lon": r["lng"], "cur": "USD", "lp": str(usd), "imgs": [], "u": r["url"],
                "days_on_market": int(dom) if dom else None, "state": r.get("state")}
        if r["kind"] == "land":
            ac = r.get("acres")
            if not ac or ac < 0.05: continue
            m2 = int(ac * 4046.86)
            b = -8 if ac < 0.25 else 0 if ac < 0.5 else 8 if ac < 1 else 16 if ac < 3 else 24 if ac < 10 else 32
            score += b; rb.append(f"size{'+' if b >= 0 else ''}{b}")
            ratio = (usd / ac) / med_upa.get(reg, usd / ac)
            vb = 12 if ratio < 0.4 else 7 if ratio < 0.7 else 3 if ratio < 1.0 else 0 if ratio < 1.6 else -4 if ratio < 2.6 else -8
            if vb: score += vb; rb.append(f"val{'+' if vb > 0 else ''}{vb}")
            rows.append({**base, "tp": "land", "r": round(score, 1), "ac": ac, "m2": m2, "upm": round(usd / m2, 1),
                         "t": r.get("ptype", ""), "name": f"{r.get('address', '')}, {r.get('city', '')} {r.get('state', '')}".strip(", ")[:180],
                         "rb": "+".join(rb)})
        else:
            sqft = r.get("sqft_living")
            if not sqft or sqft < 300 or usd < 40000: continue
            living_m2 = int(sqft * 0.092903)
            ratio = (usd / sqft) / med_ppsf.get(reg, usd / sqft)
            vb = 12 if ratio < 0.6 else 7 if ratio < 0.8 else 3 if ratio < 1.0 else 0 if ratio < 1.3 else -4 if ratio < 1.8 else -8
            if vb: score += vb; rb.append(f"val{'+' if vb > 0 else ''}{vb}")
            b = -4 if sqft < 900 else 0 if sqft < 1500 else 5 if sqft < 2500 else 9
            score += b; rb.append(f"living{'+' if b >= 0 else ''}{b}")
            ac = r.get("acres") or 0
            if ac >= 1: score += 5; rb.append("lot≥1ac+5")
            beds = int(r["beds"]) if r.get("beds") else None
            rows.append({**base, "tp": "house", "r": round(score, 1), "ac": round(ac, 3), "m2": living_m2,
                         "upm": round(usd / living_m2, 1), "t": r.get("ptype", ""), "beds": beds, "baths": r.get("baths"),
                         "living_m2": living_m2, "sqft_living": int(sqft), "plot_m2": int(ac * 4046.86) if ac else None,
                         "year_built": int(r["year"]) if r.get("year") else None, "hoa": int(r["hoa"]) if r.get("hoa") else None,
                         "usd_per_sqft": round(usd / sqft),
                         "name": f"{beds or '?'}bd {r.get('address', '')}, {r.get('city', '')} {r.get('state', '')}"[:180],
                         "rb": "+".join(rb)})
    json.dump(existing + rows, open(PATH, "w"), separators=(",", ":"))
    print(f"merged {len(rows)} US rows {dict(Counter(r['tp'] for r in rows))}; computing distances...", file=sys.stderr)
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "global_distances.py"), PATH], check=True)
    d = json.load(open(PATH))
    keep, rest = [], []
    for r in d:
        if SRC in (r.get("rb") or ""):
            c, s = r.get("coast_km"), r.get("ski_km")
            special = (c is not None and c <= 1.5) or (s is not None and s <= 5)
            (keep if special else rest).append(r)
            if special and c is not None and c <= 0.15: r["v"] = "waterfront"
        else:
            keep.append(r)
    keep.sort(key=lambda x: x.get("r", 0), reverse=True)
    json.dump(keep, open(PATH, "w"), separators=(",", ":"))
    os.makedirs(os.path.dirname(REST), exist_ok=True)
    json.dump(rest, gzip.open(REST, "wt"), separators=(",", ":"))
    kept = [r for r in keep if SRC in (r.get("rb") or "")]
    print(f"kept {len(kept)} oceanfront/ski US rows {dict(Counter(r['tp'] for r in kept))}, archived {len(rest)} -> {REST}", file=sys.stderr)
    print("by region:", Counter(r["rg"] for r in kept).most_common(40), file=sys.stderr)

if __name__ == "__main__":
    main()
