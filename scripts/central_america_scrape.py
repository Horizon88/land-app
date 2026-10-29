"""realtor.com/international land in Central America, with descriptions for the shortlist.

Crawls /international/<cc>/land for Costa Rica, Panama, Nicaragua, Belize, El Salvador,
Guatemala and Honduras (Apollo cache on each list page: price, land size, lat/lng,
tagline, photos), then fetches the listing page for every candidate that could pass
the 2-of-3 rule in ca_signals.py (10+ acres, or a tagline mentioning a view/waterfall)
to read its full description. Emits /tmp/central_america.json.

Usage: python3 scripts/central_america_scrape.py [cc,cc,...]
"""
import json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from realtor_intl_scrape import fetch, apollo_of
from ca_signals import VIEW, WATERFALL, BIG_ACRES

COUNTRIES = {"cr": "Costa Rica", "pa": "Panama", "ni": "Nicaragua", "bz": "Belize",
             "sv": "El Salvador", "gt": "Guatemala", "hn": "Honduras"}
OUT = "/tmp/central_america.json"
IMG = "https://s1.rea.global/img/raw/"

def crawl(cc, name, max_pages=250):
    rows = {}
    for page in range(1, max_pages + 1):
        html = fetch(f"https://www.realtor.com/international/{cc}/land" + ("" if page == 1 else f"/p{page}"))
        a = apollo_of(html)
        def deref(v):
            if isinstance(v, dict) and v.get("type") == "id": return a.get(v["id"], {})
            if isinstance(v, dict) and v.get("type") == "json": return v["json"]
            return v
        def gk(o, prefix):
            for k in o:
                if k.startswith(prefix): return deref(o[k])
            return None
        new = 0
        for k, r in a.items():
            if not k.startswith("ListingDetail:") or not isinstance(r, dict) or "." in k: continue
            url, geo, price = gk(r, "detailPageUrl("), deref(r.get("geoLocation")), gk(r, "price(")
            if not (url and isinstance(geo, dict) and geo.get("latitude") and price): continue
            m = re.search(r"\$([\d,]+)", (price or {}).get("displayConsumerPrice", "") if isinstance(price, dict) else "")
            if not m: continue
            land = gk(r, "landSize(")
            try: sqft = float(str(land).replace(",", "")) if land else None
            except Exception: sqft = None
            full = "https://www.realtor.com" + url
            if full in rows: continue
            photos = []
            for ph in (r.get("photos") or [])[:6]:
                o = deref(ph)
                if isinstance(o, dict) and o.get("path"): photos.append(IMG + o["path"])
            rows[full] = {"country": name, "cc": cc, "usd": int(m.group(1).replace(",", "")), "sqft": sqft,
                          "acres": round(sqft / 43560, 2) if sqft else None,
                          "lat": round(float(geo["latitude"]), 6), "lng": round(float(geo["longitude"]), 6),
                          "addr": (r.get("displayAddress") or "")[:140], "tagline": (r.get("tagline") or "")[:200],
                          "beds": r.get("bedrooms"), "types": gk(r, "propertyTypes(") or [],
                          "photos": photos, "url": full, "id": r.get("id")}
            new += 1
        if page % 10 == 0 or new == 0:
            print(f"  {name} p{page}: +{new} (total {len(rows)})", file=sys.stderr)
        if new == 0: break
        time.sleep(0.4)
    return list(rows.values())

def describe(row):
    html = fetch(row["url"], timeout=40)
    a = apollo_of(html)
    for k, v in a.items():
        if k.startswith("ListingDetail:") and isinstance(v, dict) and v.get("description"):
            row["desc"] = v["description"][:4000]; break
    return row

def main(ccs):
    out = []
    for cc in ccs:
        out += crawl(cc, COUNTRIES[cc])
        json.dump(out, open(OUT, "w"), ensure_ascii=False)
    cand = [r for r in out if (r.get("acres") or 0) >= BIG_ACRES or VIEW.search(r["tagline"]) or WATERFALL.search(r["tagline"])]
    print(f"{len(out)} land listings; fetching descriptions for {len(cand)} candidates", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, _ in enumerate(ex.map(describe, cand), 1):
            if i % 100 == 0:
                print(f"  described {i}/{len(cand)}", file=sys.stderr); json.dump(out, open(OUT, "w"), ensure_ascii=False)
    json.dump(out, open(OUT, "w"), ensure_ascii=False)
    print(f"TOTAL {len(out)} -> {OUT} ({sum(1 for r in out if r.get('desc'))} with descriptions)", file=sys.stderr)

if __name__ == "__main__":
    main((sys.argv[1] if len(sys.argv) > 1 else ",".join(COUNTRIES)).split(","))
