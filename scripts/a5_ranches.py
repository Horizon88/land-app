"""A5 Real Estate (a5realestate.com): Utah / Idaho / Nevada ranches and farms.

The home page holds every property card (available, under contract, sold). Takes
the ones still for sale (incl. under contract, flagged), reads each detail page
for more photos, pins them on the town / county named on the card (approximate)
and merges them into listings.json with rb 'src:a5'. Re-running replaces them.

Usage: python3 scripts/a5_ranches.py
"""
import html, json, os, re, subprocess, sys, time, urllib.parse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PATH = os.path.join(ROOT, "docs", "listings.json")
BASE = "https://www.a5realestate.com"
SRC = "src:a5"
STATES = {"UT": "Utah", "ID": "Idaho", "NV": "Nevada", "WY": "Wyoming"}

def get(url):
    return subprocess.run(["curl", "-sL", "--max-time", "40", "-A", "Mozilla/5.0", url], capture_output=True, text=True).stdout

def text(x):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", x)).split())

def geocode(loc):
    """Town or county from the card ('Lewiston, Cache County, Utah') -> (lat, lon)."""
    parts = [p.strip() for p in re.split(r"[|,]", loc) if p.strip()]
    state = next((STATES.get(p, p) for p in reversed(parts) if STATES.get(p, p) in STATES.values()), "Utah")
    county = [f"{p}, {state}" for p in parts if "County" in p]
    town = parts[0] if parts and not re.search(r"County|Drive|Mountains?|Mtn|Various|Canyon", parts[0]) else None
    tries = ([f"{town}, {state}"] if town else []) + county
    for q in tries:
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": q + ", USA", "format": "json", "limit": 1})
        r = subprocess.run(["curl", "-s", "--max-time", "30", "-A", "land-app/1.0", url], capture_output=True, text=True).stdout
        time.sleep(1.2)
        try:
            j = json.loads(r)
            if j: return round(float(j[0]["lat"]), 5), round(float(j[0]["lon"]), 5), state
        except Exception:
            pass
    return None, None, state

def main():
    s = get(BASE + "/")
    cards = re.findall(r'<div class="gridContentItem ([^"]*)" data-url="([^"]*)".*?background-image:url\(\'([^\']+)\'\).*?'
                       r'propertyTitle">(.*?)</h3>.*?propertyLocation">(.*?)</span>.*?propertySpecs">(.*?)</div>\s*'
                       r'<div class="description">(.*?)</div>', s, re.S)
    rows = []
    for cls, slug, img, name, loc, spec, desc in cards:
        name, loc, spec, desc = text(name), text(loc), text(spec), text(desc)
        if "sold" in cls or "SOLD" in spec: continue
        m = re.search(r"\$([\d,]+)", spec)
        a = re.search(r"([\d,.]+)\s*K?\+?\s*(?:Total\s+)?Acres", spec, re.I)
        if not m or not a: continue
        usd = int(m.group(1).replace(",", ""))
        acres = float(a.group(1).replace(",", "")) * (1000 if re.search(r"\dK\+?\s*Acres", spec) else 1)
        url = f"{BASE}/{slug}" if slug else f"{BASE}/#{urllib.parse.quote(name)}"
        imgs = [img.replace("//File", "/File")]
        if slug:
            dp = get(url)
            imgs += [BASE + u for u in re.findall(r"/File/Image/m/898/898/[0-9a-f-]+", dp)]   # gallery, large size
            imgs = list(dict.fromkeys(i.replace("//File", "/File") for i in imgs))[:12]
        lat, lon, state = geocode(loc)
        if lat is None: print(f"  {name}: no location for '{loc}'", file=sys.stderr); continue
        warn = ["map pin is the town / county centre, not the ranch"]
        if "UNDER CONTRACT" in spec.upper(): warn.insert(0, "UNDER CONTRACT: a backup offer at most")
        if "water" in (name + spec).lower() and "Ac.Ft" in spec: warn.append("price is mostly the water rights")
        m2 = int(acres * 4046.86)
        rows.append({
            "cf": "USA", "state": {v: k for k, v in STATES.items()}[state], "rg": f"{state} ranches (A5)", "a": loc[:40], "tp": "land",
            "t": "ranch / farm", "ac": acres, "m2": m2, "usd": usd, "upm": round(usd / m2, 3), "cur": "USD", "lp": str(usd),
            "lat": lat, "lon": lon, "loc_approx": True, "v": "", "imgs": imgs, "u": url, "name": f"{name}: {spec}"[:180],
            "desc": desc[:600], "perks": [f"🐎 {acres:,.0f} acres"] + (["💧 water rights"] if re.search(r"water right", desc, re.I) else [])
                    + (["🦌 hunting"] if re.search(r"hunt|elk|deer", desc, re.I) else []),
            "warn": warn, "r": 50, "rb": SRC, "source": "A5 Real Estate (a5realestate.com)",
        })
        print(f"  {name}: ${usd:,} · {acres:,.0f} ac · {loc} @ {lat},{lon} · {len(imgs)} photos", file=sys.stderr)
    d = [r for r in json.load(open(PATH)) if r.get("rb") != SRC]
    json.dump(d + rows, open(PATH, "w"), separators=(",", ":"), ensure_ascii=False)
    print(f"A5: {len(rows)} ranches for sale", file=sys.stderr)
    if rows:
        subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "global_distances.py"), PATH], check=True)

if __name__ == "__main__":
    main()
