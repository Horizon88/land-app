"""Build the swipe deck: the best oceanfront / ski / great-view listings, one card each,
with a local photo (the listing's first photo, or a satellite view of the spot when
the listing has none), for the Plot Swipe artifact.

Writes <out>/deck.json and <out>/img/<code>.jpg (~720 px wide JPEGs).
Usage: python3 scripts/swipe_deck.py <out_dir> [cards]
"""
import io, json, math, os, subprocess, sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
QUOTA = {"Japan": 75, "USA": 75, "Costa Rica": 25, "Canada": 15, "Thailand": 12, "Austria": 12}
OTHER = 4                  # every other country

def aerial(lat, lon, w_km=0.5, h_km=0.36):
    dx = w_km / 2 / (111.32 * math.cos(math.radians(lat))); dy = h_km / 2 / 110.57
    return ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?"
            f"bbox={lon-dx:.5f},{lat-dy:.5f},{lon+dx:.5f},{lat+dy:.5f}&bboxSR=4326&imageSR=3857&size=900,640&format=jpg&f=image")

def score(r):
    v = r.get("view_score") or 0
    c, s = r.get("coast_km"), r.get("ski_km")
    sea = 22 if (c is not None and c <= 0.1) else 14 if (c is not None and c <= 0.3) else 6 if (c is not None and c <= 1) else 0
    ski = 22 if (s is not None and s <= 0.3) else 14 if (s is not None and s <= 1) else 0
    tag = 10 if r.get("v") in ("beachfront", "waterfront") else 5 if r.get("v") == "sea_view" else 0
    photo = 8 if r.get("imgs") else 0
    return v * 0.7 + max(sea, ski) + tag + photo - (12 if r.get("loc_approx") else 0)

def special(r):
    c, s = r.get("coast_km"), r.get("ski_km")
    return ((c is not None and c <= 0.3) or (s is not None and s <= 1) or (r.get("view_score") or 0) >= 65
            or r.get("v") in ("beachfront", "waterfront")) and r.get("tp") in ("land", "house", "villa", None)

def fetch(url):
    try:
        b = subprocess.run(["curl", "-sL", "-m", "30", "-A", "Mozilla/5.0", url], capture_output=True, timeout=40).stdout
        im = Image.open(io.BytesIO(b)).convert("RGB")
        if im.width < 200: return None
        im.thumbnail((720, 720))
        out = io.BytesIO(); im.save(out, "JPEG", quality=78, optimize=True)
        return out.getvalue()
    except Exception:
        return None

def main(out, n_cards):
    d = json.load(open(os.path.join(ROOT, "docs", "listings.json"))) + json.load(open(os.path.join(ROOT, "docs", "saved_plots.json")))
    arch = set(json.load(open(os.path.join(ROOT, "docs", "archived.json"))).get("archives", {}))
    hidden = set(json.load(open(os.path.join(ROOT, "docs", "prefs.json"))).get("hidden_countries", []))
    pool = defaultdict(list)
    for r in d:
        if r.get("cf") in hidden or not r.get("code") or r.get("u") in arch or r.get("deal") or r.get("lat") is None or not r.get("usd"): continue
        if special(r): pool[r["cf"]].append(r)
    # guaranteed quota per country, then interleave so countries alternate (best first)
    queues = {}
    for cf, rows in pool.items():
        rows.sort(key=score, reverse=True)
        queues[cf] = rows[:QUOTA.get(cf, OTHER)]
    picks, taken = [], defaultdict(int)
    while len(picks) < n_cards and any(queues.values()):
        cf = max((c for c in queues if queues[c]), key=lambda c: score(queues[c][0]) - 6 * taken[c] * 75 / QUOTA.get(c, OTHER * 4))
        picks.append(queues[cf].pop(0)); taken[cf] += 1
    os.makedirs(os.path.join(out, "img"), exist_ok=True)

    def card(r):
        src = (r.get("imgs") or [None])[0]
        jpg = fetch(src) if src and src.startswith("http") else None
        sat = False
        if not jpg:
            jpg = fetch(aerial(r["lat"], r["lon"])); sat = True
        if not jpg: return None
        open(os.path.join(out, "img", f"{r['code']}.jpg"), "wb").write(jpg)
        c, s = r.get("coast_km"), r.get("ski_km")
        return {"code": r["code"], "u": r["u"], "cf": r["cf"], "rg": r.get("rg") or "", "a": r.get("a") or "",
                "tp": r.get("tp") or "land", "name": (r.get("name") or "")[:140], "usd": r["usd"],
                "ac": r.get("ac"), "m2": r.get("m2"), "living_m2": r.get("living_m2"), "beds": r.get("beds"),
                "year": r.get("year_built"), "coast_km": c, "ski_km": s, "ski_r": r.get("ski_r") or "",
                "view": r.get("view_score"), "view_deg": r.get("view_deg"), "v": r.get("v") or "",
                "approx": bool(r.get("loc_approx")), "sat": sat, "perks": (r.get("perks") or [])[:3],
                "warn": (r.get("warn") or [])[:2], "img": f"img/{r['code']}.jpg"}

    with ThreadPoolExecutor(max_workers=10) as ex:
        cards = [c for c in ex.map(card, picks) if c]
    json.dump({"built": __import__("time").strftime("%Y-%m-%d"), "cards": cards},
              open(os.path.join(out, "deck.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    from collections import Counter
    size = sum(os.path.getsize(os.path.join(out, "img", f)) for f in os.listdir(os.path.join(out, "img")))
    print(f"{len(cards)} cards · {size/1e6:.1f} MB images · satellite {sum(c['sat'] for c in cards)} · "
          f"{dict(Counter(c['cf'] for c in cards))}", file=sys.stderr)

if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 240)
