"""mudah.my — Malaysia land classifieds scrape.

mudah.my (Malaysia's big classifieds) exposes land ads in the page's
__NEXT_DATA__ at props.pageProps.initialStore.ads (40/page, paginate ?o=N;
meta.totalResults ~14k). Each ad has price (RM), size + sizeSuffix, title
type (Freehold / Leasehold / Malay Reserved), property type, region +
subarea, and a working adviewUrl — but NO coordinates, so we geocode by
"subarea, region, Malaysia" (Nominatim, cached like the SUUMO scraper).

Emits /tmp/mudah.json for mudah_merge.py.
"""
import json, os, re, subprocess, sys, time, urllib.parse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
OUT = "/tmp/mudah.json"
GEO_CACHE = "/tmp/mudah_geo.json"
MAX_PAGES = int(sys.argv[1]) if len(sys.argv) > 1 else 60

# state centroids (fallback when a subarea won't geocode)
STATE_CENTROID = {
    "Kuala Lumpur": (3.139, 101.687), "Selangor": (3.35, 101.35),
    "Penang": (5.35, 100.28), "Johor": (1.85, 103.35), "Perak": (4.60, 101.09),
    "Kedah": (6.12, 100.37), "Melaka": (2.20, 102.25), "Malacca": (2.20, 102.25),
    "Negeri Sembilan": (2.73, 102.10), "Pahang": (3.80, 102.40),
    "Terengganu": (5.02, 103.00), "Kelantan": (6.05, 102.20),
    "Perlis": (6.44, 100.20), "Sabah": (5.40, 116.30), "Sarawak": (2.50, 112.50),
    "Putrajaya": (2.93, 101.69), "Labuan": (5.28, 115.24),
}

def curl(url, timeout=30):
    try:
        return subprocess.run(["curl", "-sk", "-m", str(timeout), "-A", UA,
                               "-H", "Accept-Language: en", url],
                              capture_output=True, text=True, timeout=timeout + 5).stdout
    except Exception:
        return ""

def ads_of(html):
    m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return [], None
    try:
        pp = json.loads(m.group(1))["props"]["pageProps"]["initialStore"]
        return pp.get("ads", []), (pp.get("meta") or {}).get("totalResults")
    except Exception:
        return [], None

def to_sqm(size, suffix, title=""):
    try:
        v = float(str(size).replace(",", ""))
    except Exception:
        return None
    s = (suffix or "").lower()
    t = (title or "").lower()
    # title often states the true unit even when the suffix field is wrong
    title_sqft = bool(re.search(r'sq\.?\s*ft|sqft|square\s*f(?:ee|oo)t|kaki persegi|kps', t))
    title_acre = bool(re.search(r'\backer?s?\b|ekar', t))
    if "acre" in s:
        # sellers routinely mis-pick "Acre" for a sq-ft figure. A real parcel
        # of this many acres at this price would be absurd → treat as sq ft.
        if title_sqft and not title_acre:
            return round(v * 0.092903, 1)
        return round(v * 4046.86, 1)
    if "hectare" in s: return round(v * 10000, 1)
    if "feet" in s or "ft" in s or "sqft" in s: return round(v * 0.092903, 1)
    if "meter" in s or "metre" in s or "sqm" in s: return round(v, 1)
    return round(v * 0.092903, 1)          # mudah's residential default is sq ft

# titles that mean a BUILDING (not land) miscategorised under land-for-sale
BUILDING_RE = re.compile(
    r'shop\s?lot|shoplot|shop\s?house|shophouse|factory|kilang|warehouse|gudang|'
    r'apartment|pangsapuri|condo|\boffice\b|pejabat|\bstorey\b|tingkat|'
    r'semi-?d\b|terrace\s+house|double\s+storey|single\s+storey', re.I)
RENT_RE = re.compile(r'for\s*rent|untuk\s*disewa|\bdisewa\b|\bsewa\b|\brental\b', re.I)

def is_landish(title):
    t = title or ""
    if RENT_RE.search(t):
        return False
    if BUILDING_RE.search(t):
        return False
    return True

def geocode(subarea, region, cache):
    key = f"{subarea}|{region}"
    if key in cache:
        return cache[key]
    for q in (f"{subarea}, {region}, Malaysia", f"{region}, Malaysia"):
        body = curl("https://nominatim.openstreetmap.org/search?format=json&limit=1&q=" +
                    urllib.parse.quote(q), timeout=20)
        time.sleep(1.1)
        try:
            j = json.loads(body)
        except Exception:
            j = []
        if j:
            cache[key] = [round(float(j[0]["lat"]), 5), round(float(j[0]["lon"]), 5), "osm"]
            json.dump(cache, open(GEO_CACHE, "w"))
            return cache[key]
    la, lo = STATE_CENTROID.get(region, (4.2, 102.0))
    cache[key] = [la, lo, "state"]
    json.dump(cache, open(GEO_CACHE, "w"))
    return cache[key]

def main():
    out = {}
    if os.path.exists(OUT):
        for r in json.load(open(OUT)):
            out[r["id"]] = r
    cache = json.load(open(GEO_CACHE)) if os.path.exists(GEO_CACHE) else {}

    for page in range(1, MAX_PAGES + 1):
        url = "https://www.mudah.my/malaysia/land-for-sale" + ("" if page == 1 else f"?o={page}")
        ads, total = ads_of(curl(url))
        if not ads:
            print(f"  page {page}: no ads (stop)", file=sys.stderr)
            break
        new = 0
        for ad in ads:
            a = ad.get("attributes") or {}
            lid = str(a.get("listId") or ad.get("id") or "")
            if not lid or lid in out:
                continue
            title = (a.get("subject") or "")[:200]
            if not is_landish(title):
                continue                       # skip buildings / rentals
            price = a.get("price")
            sqm = to_sqm(a.get("size"), a.get("sizeSuffix"), title)
            adurl = a.get("adviewUrl")
            if not price or not sqm or not adurl:
                continue
            price = int(float(price))
            # price-sanity unit correction: a genuine >50-acre parcel is never
            # this cheap per acre → the "Acre" figure was really sq ft.
            if "acre" in (a.get("sizeSuffix") or "").lower():
                acres = sqm / 4046.86
                if acres > 50 and (price / acres) < 3000:
                    sqm = round(float(str(a.get("size")).replace(",", "")) * 0.092903, 1)
            out[lid] = {
                "id": lid, "url": adurl, "title": title,
                "price_rm": price,
                "sqm": sqm, "size_raw": a.get("size"), "size_suffix": a.get("sizeSuffix"),
                "region": a.get("regionName") or "", "subarea": a.get("subareaName") or "",
                "title_type": a.get("titleTypeName") or "",
                "property_type": a.get("propertyTypeName") or "",
                "date": a.get("date") or "",
                "img": ("https://img.rnudah.com/images" + a["image"]) if a.get("image") else "",
            }
            new += 1
        print(f"  page {page}: {len(ads)} ads, {new} new (total {len(out)} / {total})", file=sys.stderr)
        if page % 5 == 0:
            json.dump(list(out.values()), open(OUT, "w"))
        time.sleep(0.3)

    # geocode unique localities
    uniq = {(r["subarea"], r["region"]) for r in out.values()}
    print(f"geocoding {len(uniq)} unique localities…", file=sys.stderr)
    for sub, reg in uniq:
        geocode(sub, reg, cache)
    for r in out.values():
        g = cache.get(f"{r['subarea']}|{r['region']}")
        if g:
            r["lat"], r["lng"], r["geo_src"] = g[0], g[1], g[2]

    json.dump(list(out.values()), open(OUT, "w"))
    coded = sum(1 for r in out.values() if r.get("lat"))
    print(f"TOTAL {len(out)} mudah land rows ({coded} geocoded) -> {OUT}", file=sys.stderr)

if __name__ == "__main__":
    main()
