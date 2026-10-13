"""willhaben.at — Austria alpine land scrape (for ski-in/ski-out hunting).

willhaben (Austria's dominant classifieds) embeds land ads in __NEXT_DATA__
at props.pageProps.searchResult.advertSummaryList.advertSummary (30/page,
paginate ?page=N). Each ad's `attributes` carry PRICE (€), ESTATE_SIZE (m²),
COORDINATES (lat,lng — no geocoding needed!), LOCATION/STATE/DISTRICT, and a
SEO_URL. We scrape the five alpine states; the merge keeps only listings near
a ski resort and flags ski-in/ski-out. Emits /tmp/willhaben.json.
"""
import json, os, re, subprocess, sys, time

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
OUT = "/tmp/willhaben.json"
ALPINE = ["tirol", "salzburg", "vorarlberg", "kaernten", "steiermark"]
ALL_STATES = ALPINE + ["wien", "niederoesterreich", "oberoesterreich", "burgenland"]
# (category-path, kind, states, max pages) — land everywhere, chalets in the
# alpine states, apartments in Vienna
JOBS = [("grundstuecke", "land", ALL_STATES, 45),
        ("haus-kaufen", "house", ALPINE, 45),
        ("eigentumswohnung", "apartment", ["wien"], 80)]

def curl(url, timeout=30):
    try:
        return subprocess.run(["curl", "-sk", "-m", str(timeout), "-A", UA, url],
                              capture_output=True, text=True, timeout=timeout + 5).stdout
    except Exception:
        return ""

def page_ads(html):
    m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return [], None
    try:
        sr = json.loads(m.group(1))["props"]["pageProps"]["searchResult"]
        return sr["advertSummaryList"]["advertSummary"], sr.get("rowsFound")
    except Exception:
        return [], None

def gv(ad, name):
    for x in ad.get("attributes", {}).get("attribute", []):
        if x["name"] == name and x.get("values"):
            return x["values"][0]
    return None

def main():
    out = {}
    if os.path.exists(OUT):
        for r in json.load(open(OUT)):
            out[r["id"]] = r
    for cat, kind, states, max_pages in JOBS:
        for state in states:
            got = 0; total = None
            for pg in range(1, max_pages + 1):
                url = f"https://www.willhaben.at/iad/immobilien/{cat}/{state}/" + (f"?page={pg}" if pg > 1 else "")
                ads, total = page_ads(curl(url))
                if not ads:
                    break
                new = 0
                for ad in ads:
                    lid = str(ad.get("id") or gv(ad, "ADID") or "")
                    if not lid or lid in out:
                        continue
                    coords = gv(ad, "COORDINATES")
                    price = gv(ad, "PRICE")
                    seo = gv(ad, "SEO_URL")
                    if not (coords and price and seo):
                        continue
                    if kind == "land":
                        size = gv(ad, "ESTATE_SIZE") or gv(ad, "PLOT/AREA")
                    else:  # house/apartment: ESTATE_SIZE is living area; FREE_AREA is the plot
                        size = gv(ad, "ESTATE_SIZE/LIVING_AREA") or gv(ad, "ESTATE_SIZE")
                    if not size:
                        continue
                    try:
                        lat, lng = [float(x) for x in coords.split(",")]
                        eur = int(float(price)); sqm = float(size)
                    except Exception:
                        continue
                    imgs = gv(ad, "ALL_IMAGE_URLS") or ""
                    plot = gv(ad, "FREE_AREA/FREE_AREA_AREA_TOTAL")
                    out[lid] = {
                        "id": lid, "kind": kind,
                        "url": "https://www.willhaben.at/iad/" + seo.lstrip("/"),
                        "title": (gv(ad, "HEADING") or ad.get("description") or "")[:200],
                        "eur": eur, "sqm": sqm, "lat": lat, "lng": lng,
                        "living_m2": (float(size) if kind != "land" else None),
                        "floor": gv(ad, "FLOOR"),
                        "plot_m2": (float(plot) if plot else None),
                        "rooms": gv(ad, "NUMBER_OF_ROOMS"),
                        "location": gv(ad, "LOCATION") or "", "state": gv(ad, "STATE") or state.title(),
                        "district": gv(ad, "DISTRICT") or "", "postcode": gv(ad, "POSTCODE") or "",
                        "ptype": gv(ad, "PROPERTY_TYPE") or "",
                        "published": (gv(ad, "PUBLISHED_String") or "")[:10],
                        "img": ("https://cache.willhaben.at/mmo/" + imgs.split(";")[0]) if imgs else "",
                    }
                    new += 1; got += 1
                if new == 0:
                    break
                time.sleep(0.3)
            print(f"  {cat}/{state}: +{got} (of {total}); total {len(out)}", file=sys.stderr)
            json.dump(list(out.values()), open(OUT, "w"))
    json.dump(list(out.values()), open(OUT, "w"))
    from collections import Counter
    print(f"TOTAL {len(out)} willhaben rows ({dict(Counter(r['kind'] for r in out.values()))}) -> {OUT}", file=sys.stderr)

if __name__ == "__main__":
    main()
