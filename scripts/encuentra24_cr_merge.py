"""Merge Encuentra24 Costa Rica (/tmp/encuentra24_cr.json) into listings.json.

Tiles only give a district name, so rows are geocoded to the district
(Nominatim, cached in scripts/geo/geo_cache_cr.json) and flagged loc_approx.
Ocean signals come from the listing text (beachfront / ocean view, English and
Spanish). Kept in the app: anything with ocean wording, anything whose district
is within 10 km of the sea, and big farms (50+ acres, the eco-resort type);
the rest goes to data/raw/costa_rica.json.gz.
"""
import gzip, json, os, re, subprocess, sys, time, urllib.parse, urllib.request
from collections import Counter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RAW = "/tmp/encuentra24_cr.json"
PATH = os.path.join(ROOT, "docs", "listings.json")
CACHE = os.path.join(ROOT, "scripts", "geo", "geo_cache_cr.json")
REST = os.path.join(ROOT, "data", "raw", "costa_rica.json.gz")
SRC = "src:encuentra24-cr"
BEACH = re.compile(r"beach ?front|ocean ?front|frente al mar|frente a la playa|frente de playa|on the beach|sobre la playa|water ?front", re.I)
VIEW = re.compile(r"ocean views?|sea views?|vista al mar|vistas al mar|vista(?:s)? (?:al|del) oc[eé]ano|panoramic ocean", re.I)
RIVER = re.compile(r"\briver\b|\br[ií]o\b|waterfall|catarata|quebrada", re.I)
FOREIGN = ("Costa Rica: foreigners can own titled land like citizens. Exception: the Maritime-Terrestrial Zone, "
           "the first 200 m from high tide. The first 50 m are public; the next 150 m are municipal concessions "
           "(not titled), and a foreigner may hold at most 49% of a concession. Check whether a beach lot is titled or a concession.")

def geocode(names):
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    for n in sorted(set(names) - set(cache)):
        q = urllib.parse.quote(f"{n}, Costa Rica")
        try:
            req = urllib.request.Request(f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=1&countrycodes=cr",
                                         headers={"User-Agent": "land-app/1.0 (personal research)"})
            res = json.load(urllib.request.urlopen(req, timeout=30))
            cache[n] = [round(float(res[0]["lat"]), 5), round(float(res[0]["lon"]), 5)] if res else None
        except Exception:
            cache[n] = None
        time.sleep(1.05)
    json.dump(cache, open(CACHE, "w"), ensure_ascii=False, indent=0)
    return cache

def main():
    raw = json.load(open(RAW))
    geo = geocode([r["location"] for r in raw if r.get("location")])
    existing = [e for e in json.load(open(PATH)) if SRC not in (e.get("rb") or "")]
    rows = []
    for r in raw:
        g = geo.get(r.get("location"))
        if not g or not r.get("usd") or r["usd"] < 5000: continue
        txt = f"{r.get('title', '')} {r.get('desc', '')}"
        v = "beachfront" if BEACH.search(txt) else "sea_view" if VIEW.search(txt) else ""
        m2 = r.get("m2") or 0
        rb = [SRC, "base+20"]; score = 20
        if v == "beachfront": score += 20; rb.append("beachfront+20")
        elif v == "sea_view": score += 12; rb.append("seaview+12")
        if RIVER.search(txt): score += 4; rb.append("river+4")
        base = {"cf": "Costa Rica", "rg": r.get("location") or "", "a": r.get("location") or "", "usd": r["usd"],
                "cur": r["cur"], "lp": str(int(r["amount"])), "lat": g[0], "lon": g[1], "loc_approx": True,
                "v": v, "el": "", "u": r["url"], "imgs": [r["img"]] if r.get("img") else [],
                "name": (r.get("title") or "")[:180], "desc": (r.get("desc") or "")[:400], "foreign_note": FOREIGN}
        if r["kind"] in ("land", "farm"):
            if m2 < 100: continue
            ac = round(m2 / 4046.86, 3)
            b = -6 if ac < 0.1 else 0 if ac < 0.5 else 6 if ac < 2 else 12 if ac < 10 else 18
            score += b; rb.append(f"size{'+' if b >= 0 else ''}{b}")
            rows.append({**base, "tp": "land", "t": "farm" if r["kind"] == "farm" else "lot", "ac": ac, "m2": int(m2),
                         "upm": round(r["usd"] / m2, 1), "r": score, "rb": "+".join(rb)})
        else:
            nums = [d for d in r.get("details", [])[1:] if re.fullmatch(r"[\d\.]+", d)]
            beds = int(float(nums[0])) if nums else None
            rows.append({**base, "tp": "house", "t": "house", "ac": 0, "m2": int(m2) if m2 else None,
                         "living_m2": int(m2) if m2 else None, "beds": beds,
                         "upm": round(r["usd"] / m2, 1) if m2 else None, "r": score, "rb": "+".join(rb)})
    json.dump(existing + rows, open(PATH, "w"), separators=(",", ":"))
    print(f"merged {len(rows)} Costa Rica rows; distances...", file=sys.stderr)
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "global_distances.py"), PATH], check=True)
    d = json.load(open(PATH)); keep, rest = [], []
    for r in d:
        if SRC in (r.get("rb") or ""):
            c = r.get("coast_km")
            ok = r.get("v") in ("beachfront", "sea_view") or (c is not None and c <= 10) or (r.get("ac") or 0) >= 50
            (keep if ok else rest).append(r)
        else:
            keep.append(r)
    json.dump(keep, open(PATH, "w"), separators=(",", ":"))
    os.makedirs(os.path.dirname(REST), exist_ok=True)
    json.dump(rest, gzip.open(REST, "wt"), separators=(",", ":"))
    kept = [r for r in keep if SRC in (r.get("rb") or "")]
    print(f"kept {len(kept)} Costa Rica rows {dict(Counter(r['tp'] for r in kept))} "
          f"(beachfront {sum(r['v']=='beachfront' for r in kept)}, ocean view {sum(r['v']=='sea_view' for r in kept)}, "
          f"farms 50+ ac {sum((r.get('ac') or 0)>=50 for r in kept)}); archived {len(rest)}", file=sys.stderr)
    print("by district:", Counter(r["rg"] for r in kept).most_common(15), file=sys.stderr)

if __name__ == "__main__":
    main()
