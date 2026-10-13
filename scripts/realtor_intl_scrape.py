"""realtor.com/international land scrape — small-market countries.

realtor.com's international pages embed a Next.js Apollo cache
(__NEXT_DATA__ .props.apolloState) with a ListingDetail:<id> object per
listing: price (displayConsumerPrice "USD $X"), landSize (sq ft),
geoLocation (lat/lng), displayAddress, detailPageUrl, propertyTypes.

Parameterised by ISO country code so the same parser serves any small
market. Currently: Grenada (gd). Emits /tmp/realtor_intl.json for the merge.
"""
import json, os, re, subprocess, sys, time, urllib.parse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
COUNTRIES = {"gd": "Grenada", "br": "Brazil"}          # code -> display name
OUT = "/tmp/realtor_intl.json"

def fetch(url, timeout=30):
    try:
        p = subprocess.run(["curl", "-sk", "-m", str(timeout), "-A", UA, url],
                           capture_output=True, text=True, timeout=timeout + 5)
        return p.stdout
    except Exception:
        return ""

def apollo_of(html):
    m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))["props"]["apolloState"]
    except Exception:
        return {}

def parse_country(cc, name):
    rows = {}
    for page in range(1, 6):                    # p1..; stops when a page adds nothing
        suffix = "" if page == 1 else f"/p{page}"
        html = fetch(f"https://www.realtor.com/international/{cc}/land{suffix}")
        apollo = apollo_of(html)
        def deref(v):
            if isinstance(v, dict) and v.get("type") == "id": return apollo.get(v["id"], {})
            if isinstance(v, dict) and v.get("type") == "json": return v["json"]
            return v
        def gk(o, prefix):
            for k in o:
                if k.startswith(prefix): return deref(o[k])
            return None
        new = 0
        for k, r in apollo.items():
            if not k.startswith("ListingDetail:") or not isinstance(r, dict):
                continue
            url = gk(r, "detailPageUrl(")
            geo = deref(r.get("geoLocation"))
            price = gk(r, "price(")
            if not (url and isinstance(geo, dict) and geo.get("latitude") and price):
                continue
            types = gk(r, "propertyTypes(") or []
            if "Land" not in types:
                continue
            dcp = price.get("displayConsumerPrice", "") if isinstance(price, dict) else ""
            m = re.search(r"\$([\d,]+)", dcp or "")
            usd = int(m.group(1).replace(",", "")) if m else None
            if not usd:
                continue
            land = gk(r, "landSize(")
            sqft = None
            if land:
                try: sqft = float(str(land).replace(",", ""))
                except Exception: sqft = None
            full_url = "https://www.realtor.com" + url
            if full_url in rows:
                continue
            rows[full_url] = {
                "country": name, "cc": cc, "usd": usd, "sqft": sqft,
                "lat": round(float(geo["latitude"]), 6), "lng": round(float(geo["longitude"]), 6),
                "addr": (r.get("displayAddress") or "")[:120],
                "url": full_url, "id": r.get("id"),
            }
            new += 1
        print(f"  {name} p{page}: +{new} (total {len(rows)})", file=sys.stderr)
        if new == 0:
            break
        time.sleep(0.4)
    return list(rows.values())

if __name__ == "__main__":
    out = []
    for cc, name in COUNTRIES.items():
        out += parse_country(cc, name)
    json.dump(out, open(OUT, "w"))
    print(f"TOTAL {len(out)} realtor-intl land rows -> {OUT}", file=sys.stderr)
