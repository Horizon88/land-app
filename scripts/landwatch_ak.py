"""LandWatch: all Alaska land (much of it remote, off-grid, fly-in or boat-in) -> listings.json.

Reads every result page of landwatch.com/alaska-land-for-sale through the relay
(card: id, address, price, acres, beds/baths, blurb), then each listing page for
its map position and photos. Skips lots under 1 acre (unless on the water),
listings without a price or position, and ones Redfin already has (same spot and
price). Rows carry rb 'src:landwatch-ak' and are replaced on each run.

Usage: python3 scripts/landwatch_ak.py [max_pages]
"""
import html, json, os, re, subprocess, sys, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PATH = os.path.join(ROOT, "docs", "listings.json")
RELAY = "https://landrelay.flag-theory.workers.dev/?url="
BASE = "https://www.landwatch.com"
SRC = "src:landwatch-ak"

def get(url, tries=3):
    for i in range(tries):
        out = subprocess.run(["curl", "-s", "--max-time", "60", RELAY + urllib.parse.quote(url, safe="")],
                             capture_output=True, text=True).stdout
        if len(out) > 5000: return out
        time.sleep(2 * (i + 1))
    return ""

def text(x):
    return " | ".join(t for t in (html.unescape(s).strip() for s in re.findall(r">([^<]+)<", re.sub(r"<script.*?</script>", "", x, flags=re.S))) if t)

# LandWatch shows at most 20 pages (500 cards) per search, so search each borough separately
BOROUGHS = ["aleutians-west", "anchorage", "bethel", "bristol-bay", "chugach", "copper-river", "denali", "dillingham",
            "fairbanks-north-star", "haines", "hoonah-angoon-census-area", "juneau", "kenai-peninsula", "ketchikan-gateway",
            "kodiak-island", "lake-and-peninsula", "matanuska-susitna", "nome", "north-slope", "northwest-arctic", "petersburg",
            "prince-wales-ketchikan", "sitka", "southeast-fairbanks", "wrangell", "yakutat", "yukon-koyukuk"]

def cards(page, area=""):
    path = f"{BASE}/alaska-land-for-sale" + (f"/{area}-borough" if area else "")
    s = get(path + ("" if page == 1 else f"/page-{page}"))
    out = []
    parts = re.split(r'<div id="placard-container"', s)[1:]
    for p in parts:
        pid = re.search(r'data-qa-listing="(\d+)"', p)
        href = re.search(r'href="(/[^"]+/pid/\d+)"', p)
        if not (pid and href): continue
        t = text(p[:8000])
        price = re.search(r"\$([\d,]+)", t)
        acres = re.search(r"([\d,.]+)\s*acres?", t, re.I)
        beds = re.search(r"(\d+)\s*beds?", t)
        addr = re.search(r"\|\s*([^|]*,\s*AK,\s*\d{5}[^|]*)", t)
        out.append({"pid": pid.group(1), "url": BASE + href.group(1), "price": int(price.group(1).replace(",", "")) if price else None,
                    "acres": float(acres.group(1).replace(",", "")) if acres else None, "beds": int(beds.group(1)) if beds else None,
                    "addr": addr.group(1).strip() if addr else "", "blurb": t})
    return out, (f"/page-{page + 1}") in s

def detail(c):
    s = get(c["url"])
    ll = re.search(r'"latitude":\s*(-?[0-9.]+),\s*"longitude":\s*(-?[0-9.]+)', s)
    if ll and float(ll.group(1)) != 0:
        c["lat"], c["lon"] = round(float(ll.group(1)), 5), round(float(ll.group(2)), 5)
    ids = list(dict.fromkeys(re.findall(r'https://assets\.landwatch\.com/resizedimages/[^"\'\s\\)]*?/(1-\d+)', s)))
    # LandWatch's image host refuses hotlinks from many networks; the relay serves them reliably
    c["imgs"] = [RELAY + urllib.parse.quote(f"https://assets.landwatch.com/resizedimages/1024/0/h/80/{i}", safe="") for i in ids][:10]
    d = re.search(r'"description":\s*"((?:[^"\\]|\\.){40,})"', s)
    c["desc"] = json.loads('"' + d.group(1) + '"')[:600] if d else ""
    return c

def main(max_pages):
    allc, seen = [], set()
    for area in BOROUGHS:
        page = 1
        while page <= max_pages:
            cs, more = cards(page, area)
            new = [c for c in cs if c["pid"] not in seen]
            seen.update(c["pid"] for c in new); allc += new
            if not cs or not more: break
            page += 1
        print(f"  {area}: {len(allc)} cards so far", file=sys.stderr)
    keep = [c for c in allc if c["price"] and c["acres"]]
    with ThreadPoolExecutor(max_workers=6) as ex:
        keep = list(ex.map(detail, keep))
    d = json.load(open(PATH))
    d = [r for r in d if r.get("rb") != SRC]
    redfin = {(round(r["lat"], 3), round(r["lon"], 3), r.get("usd")) for r in d if r.get("state") == "AK" and r.get("lat") is not None}
    rows = []
    for c in keep:
        if "lat" not in c: continue
        if (round(c["lat"], 3), round(c["lon"], 3), c["price"]) in redfin: continue
        house = bool(c["beds"]) or re.search(r"\b(home|house|cabin|lodge)\b", c["blurb"][:300], re.I)
        ac = c["acres"]; m2 = int(ac * 4046.86)
        name = c["addr"] or c["blurb"].split(" | ")[0]
        access = [w for w in ("fly-in", "boat access", "float plane", "off-grid", "remote", "waterfront", "river", "lake", "ocean")
                  if w in (c["desc"] + c["blurb"]).lower()]
        rows.append({"cf": "USA", "state": "AK", "rg": "Alaska (LandWatch)", "a": (c["addr"].split(",")[1].strip() if c["addr"].count(",") >= 2 else "")[:40],
                     "tp": "house" if house else "land", "t": "land" + (" + cabin/house" if house else ""), "ac": ac, "m2": m2,
                     "plot_m2": m2 if house else None, "beds": c["beds"], "usd": c["price"], "upm": round(c["price"] / m2, 3) if m2 else None,
                     "cur": "USD", "lp": str(c["price"]), "lat": c["lat"], "lon": c["lon"], "v": "", "imgs": c.get("imgs") or [],
                     "u": c["url"], "name": f"{name}: {ac:g} acres"[:180], "desc": c["desc"] or c["blurb"][:500],
                     "perks": [f"🏔 {ac:,.0f} acres"] + ([f"🛶 {', '.join(access)}"] if access else []),
                     "r": 40, "rb": SRC, "source": "LandWatch Alaska"})
    json.dump(d + rows, open(PATH, "w"), separators=(",", ":"), ensure_ascii=False)
    print(f"LandWatch Alaska: {len(allc)} cards, {len(rows)} added", file=sys.stderr)
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "global_distances.py"), PATH], check=True)
    # keep only 1+ acre, or anything within 300 m of the sea
    d = json.load(open(PATH))
    d = [r for r in d if r.get("rb") != SRC or (r.get("ac") or 0) >= 1 or (r.get("coast_km") is not None and r["coast_km"] <= 0.3)]
    json.dump(d, open(PATH, "w"), separators=(",", ":"), ensure_ascii=False)
    print(f"  kept {sum(1 for r in d if r.get('rb') == SRC)}", file=sys.stderr)

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 100)
