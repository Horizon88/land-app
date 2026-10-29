"""Merge Central America land (realtor.com/international, /tmp/central_america.json) into
listings.json, keeping only plots that pass at least 2 of 3 signals (ca_signals.py):
big land (10+ acres), Pacific Ocean view, waterfall. Each kept row carries ca_signals
so the app's Central America hunt can find and rank them.

Also re-applies the rule to the Encuentra24 Costa Rica crawl (/tmp/encuentra24_cr.json
if present): rows the coastal filter archived come back when they pass 2 of 3.
"""
import json, os, subprocess, sys
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ca_signals import signals, FOREIGN

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PATH = os.path.join(ROOT, "docs", "listings.json")
SRC = "src:realtor-ca"
LABEL = {"big": "🌳 big land", "pacific": "🌊 Pacific view", "waterfall": "💧 waterfall"}

def perks(sig, acres, pkm):
    p = []
    if "big" in sig: p.append(f"🌳 {acres:,.0f} acres")
    if "pacific" in sig: p.append(f"🌊 Pacific Ocean view ({pkm:.0f} km to the coast)")
    if "waterfall" in sig: p.append("💧 waterfall on or by the land")
    return p

def main():
    d = json.load(open(PATH))
    have = {r.get("u"): r for r in d}
    d = [r for r in d if SRC not in (r.get("rb") or "")]
    rows, n_in = [], 0
    if os.path.exists("/tmp/central_america.json"):
        for r in json.load(open("/tmp/central_america.json")):
            n_in += 1
            text = f"{r.get('tagline', '')} {r.get('desc', '')}"
            ac = r.get("acres") or 0
            sig, pkm = signals(text, r["lat"], r["lng"], ac, r["country"])
            if len(sig) < 2 or not r.get("usd") or r["usd"] < 5000: continue
            m2 = int(ac * 4046.86) if ac else None
            parts = [p.strip() for p in (r.get("addr") or "").split(",") if p.strip()]
            house = any("House" in t or "Villa" in t for t in r.get("types") or [])
            rows.append({
                "cf": r["country"], "rg": parts[-1] if parts else r["country"], "a": ", ".join(parts[:2])[:40],
                "tp": "house" if house and r.get("beds") else "land", "t": "farm / land" + (" + house" if house else ""),
                "ac": round(ac, 2), "m2": m2, "usd": r["usd"], "upm": round(r["usd"] / m2, 2) if m2 else None,
                "cur": "USD", "lp": str(r["usd"]), "lat": r["lat"], "lon": r["lng"], "v": "sea_view" if "pacific" in sig else "",
                "imgs": r.get("photos") or [], "u": r["url"], "name": (r.get("tagline") or r.get("addr") or "")[:180],
                "desc": (r.get("desc") or "")[:600], "beds": r.get("beds"),
                "ca_signals": sig, "pacific_km": pkm, "perks": perks(sig, ac, pkm),
                "r": 40 + 15 * len(sig), "rb": f"{SRC}+signals:{'/'.join(sig)}",
                "foreign_note": FOREIGN.get(r["country"], ""),
            })
    # Encuentra24 Costa Rica: tag rows already in the app, bring back archived ones that pass
    e24 = 0
    if os.path.exists("/tmp/encuentra24_cr.json"):
        by_u = {r.get("u"): r for r in d if r.get("cf") == "Costa Rica"}
        geo = json.load(open(os.path.join(ROOT, "scripts", "geo", "geo_cache_cr.json")))
        for r in json.load(open("/tmp/encuentra24_cr.json")):
            g = geo.get(r.get("location"))
            if not g: continue
            ac = (r.get("m2") or 0) / 4046.86 if r["kind"] != "house" else 0
            sig, pkm = signals(f"{r.get('title', '')} {r.get('desc', '')}", g[0], g[1], ac, "Costa Rica")
            if len(sig) < 2: continue
            row = by_u.get(r["url"])
            if row is None:
                if not r.get("usd") or r["usd"] < 5000 or not r.get("m2"): continue
                row = {"cf": "Costa Rica", "rg": r.get("location") or "", "a": r.get("location") or "", "tp": "land",
                       "t": "farm" if r["kind"] == "farm" else "lot", "ac": round(ac, 2), "m2": int(r["m2"]), "usd": r["usd"],
                       "upm": round(r["usd"] / r["m2"], 2), "cur": r["cur"], "lp": str(int(r["amount"])), "lat": g[0], "lon": g[1],
                       "loc_approx": True, "v": "", "imgs": r.get("imgs") or ([r["img"]] if r.get("img") else []), "u": r["url"],
                       "name": (r.get("title") or "")[:180], "desc": (r.get("desc") or "")[:400], "r": 40,
                       "rb": "src:encuentra24-cr+ca-2of3", "foreign_note": FOREIGN["Costa Rica"]}
                d.append(row)
            row["ca_signals"] = sig; row["pacific_km"] = pkm
            row["perks"] = list(dict.fromkeys((row.get("perks") or []) + perks(sig, ac, pkm)))
            e24 += 1
    d += rows
    json.dump(d, open(PATH, "w"), separators=(",", ":"))
    print(f"realtor.com Central America: {len(rows)} of {n_in} pass 2 of 3 · {dict(Counter(r['cf'] for r in rows))}", file=sys.stderr)
    print(f"  signal mix: {dict(Counter('+'.join(r['ca_signals']) for r in rows))}", file=sys.stderr)
    print(f"Encuentra24 Costa Rica rows passing 2 of 3: {e24}", file=sys.stderr)
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "global_distances.py"), PATH], check=True)

if __name__ == "__main__":
    main()
