"""Pick the next land deals for the club: cheap land in nice places, one country at a time.

A listing qualifies when it is land, has a photo, costs $15k-$400k, is at least 1 acre,
has no deal-killer warnings, and is in a nice setting (view score >= 55, within 500 m of
the sea, beach/waterfront, within 3 km of a ski lift, or within 300 m of a lake).
It is then ranked on setting + value (price per acre vs. similar-size land in the same
country, since big blocks are always cheaper per acre) + size.

Writes deal-club/out/picks.json: [{teaser: {...public...}, private: {...members only...}}].
The out/ folder is gitignored: this repo is public, so members-only details must never
be committed. publish.py uploads them to the paywall worker.

Usage: python3 deal-club/pick.py [count] [max_per_country]
"""
import json, os, statistics, sys
from collections import defaultdict
from datetime import date

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "deal-club", "out")
POSTED = os.path.join(ROOT, "deal-club", "posted.json")   # codes already used (public: codes only)

def load(name, default):
    try:
        return json.load(open(os.path.join(ROOT, name)))
    except FileNotFoundError:
        return default

def setting(r):
    """(points, label) for how special the spot is; 0 means not nice enough."""
    c, s, lk, v = r.get("coast_km"), r.get("ski_km"), r.get("lake_km"), r.get("view_score") or 0
    if r.get("v") in ("beachfront", "waterfront") or (c is not None and c <= 0.1):
        return 40, "Beachfront"
    if c is not None and c <= 0.5:
        return 32, f"{int(c * 1000)} m from the sea"
    if r.get("v") in ("sea_view", "sea_visible"):
        return 28, "Sea views"
    if s is not None and s <= 3:
        return 30, f"{s:.1f} km to the ski lifts" + (f" ({r['ski_r']})" if r.get("ski_r") else "")
    if lk is not None and lk <= 0.3:
        return 28, "Lakeside" + (f" ({r['lake']})" if r.get("lake") else "")
    if v >= 55:
        return 20 + (v - 55) // 3, "Big views"
    return 0, ""

def main(count=7, per_country=2):
    rows = load("docs/listings.json", [])
    arch = set(load("docs/archived.json", {}).get("archives", {}))
    posted = set(load("deal-club/posted.json", []))
    hidden = set(load("docs/prefs.json", {}).get("hidden_countries", []))

    land = [r for r in rows if r.get("tp") == "land" and r.get("usd") and r.get("ac")]
    by_country = defaultdict(list)
    for r in land:
        by_country[r["cf"]].append((r["ac"], r["usd"] / r["ac"]))

    def median(r):
        """Median price per acre of same-country land between half and twice this size."""
        near = [p for a, p in by_country[r["cf"]] if r["ac"] / 2 <= a <= r["ac"] * 2]
        return statistics.median(near) if len(near) >= 15 else None

    cands = []
    for r in land:
        if (r.get("u") in arch or r.get("code") in posted or r.get("cf") in hidden or r.get("warn")
                or r.get("loc_approx") or not r.get("imgs") or not r.get("u") or not r.get("code")
                or not 15000 <= r["usd"] <= 400000 or r["ac"] < 1):
            continue
        pts, label = setting(r)
        if not pts or not (med := median(r)):
            continue
        value = med / (r["usd"] / r["ac"])            # 2.0 = half the usual price per acre
        if value > 6:                                  # too good to be true: usually a bad price or area
            continue
        score = pts + min(value, 4) * 10 + min(r["ac"], 50) ** 0.5 * 3 + (5 if len(r["imgs"]) >= 3 else 0)
        cands.append((score, value, med, label, r))

    cands.sort(key=lambda x: x[0], reverse=True)
    picks, used = [], defaultdict(int)
    for score, value, med, label, r in cands:
        if used[r["cf"]] >= per_country:
            continue
        used[r["cf"]] += 1
        place = r["cf"] if not r.get("rg") else f"{r['rg']}, {r['cf']}"
        highlights = [label, f"{r['ac']:,.1f} acres"]
        if value >= 1.5:
            highlights.append(f"{value:.1f}x cheaper per acre than similar-size land in {r['cf']}")
        if (r.get("view_score") or 0) >= 55 and label != "Big views":
            highlights.append(f"View score {r['view_score']}/100")
        if r.get("total_drop_pct"):
            highlights.append(f"Price cut {r['total_drop_pct']:.0f}%")
        picks.append({
            "teaser": {   # safe to show anyone (Instagram, landing page)
                "code": r["code"], "country": r["cf"], "region": r.get("rg") or "",
                "acres": round(r["ac"], 1), "usd": int(r["usd"]), "headline": label,
                "highlights": highlights, "photos": r["imgs"][:6],
            },
            "private": {  # members only
                "code": r["code"], "place": place, "area": r.get("a") or "",
                "lat": r.get("lat"), "lon": r.get("lon"), "url": r["u"], "title": r.get("name") or r.get("t") or "",
                "price_local": f"{r.get('lp')} {r.get('cur')}" if r.get("lp") else "",
                "usd_per_acre": int(r["usd"] / r["ac"]), "similar_size_median_usd_per_acre": int(med),
                "coast_km": r.get("coast_km"), "ski_km": r.get("ski_km"), "view_score": r.get("view_score"),
                "foreign_note": r.get("foreign_note") or "", "picked": date.today().isoformat(),
            },
        })
        if len(picks) >= count:
            break

    os.makedirs(OUT, exist_ok=True)
    json.dump(picks, open(os.path.join(OUT, "picks.json"), "w"), indent=1, ensure_ascii=False)
    for p in picks:
        t = p["teaser"]
        print(f"{t['code']}  ${t['usd']:>8,}  {t['acres']:>6} ac  {t['country']:<12} {t['headline']}")
    print(f"\n{len(picks)} picks from {len(cands)} candidates -> deal-club/out/picks.json")

if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:3]))
