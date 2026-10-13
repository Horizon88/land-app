"""PropertyHub.in.th — Thai land scrape (v2, post-restructure).

PropertyHub moved to a Next.js SPA. Listings now live in the page's
__NEXT_DATA__ at props.pageProps.resultListings (60/page), and the working
detail URL is  /en/listings/<slug>---<id>  (triple dash). The old
/<thai-slug> URLs 404, which is why the previous scraper died.

Server-side pagination isn't exposed (?page= is ignored — the site paginates
client-side via XHR the relay can't drive), so we fetch the first page of
each South-province land feed (~60 listings, default-sorted = freshest).
Province slugs use PropertyHub's own spellings; a bad slug falls back to the
all-Thailand feed, which the South-Thailand bounding-box filter discards.
Emits /tmp/propertyhub_th.json for the merge.
"""
import json, os, re, subprocess, sys, time, urllib.parse

RELAY = "https://landrelay.flag-theory.workers.dev"
OUT = "/tmp/propertyhub_th.json"
# South-Thailand bounding box (Andaman + southern Gulf incl. Prachuap/Hua Hin)
S_LAT = (5.5, 12.7); S_LNG = (97.3, 100.9)

# PropertyHub province slugs (their spellings) for the southern hunt provinces.
# Bad/duplicate spellings are harmless — the bbox filter drops any that fall
# back to the all-Thailand feed.
PROVINCE_SLUGS = [
    "phuket", "krabi", "phangnga", "surat-thani", "trang", "chumphon",
    "ranong", "satun", "songkhla", "prachaubkirikhan",
    "nakhon-si-thammarat", "nakhonsithammarat", "pattani",
]

# recognizable southern provinces for labelling from the address string
S_PROVINCES = ["Phuket", "Krabi", "Phang Nga", "Phangnga", "Surat Thani",
               "Nakhon Si Thammarat", "Trang", "Chumphon", "Ranong", "Satun",
               "Songkhla", "Pattani", "Yala", "Narathiwat", "Prachuap Khiri Khan"]

def via_relay(url, timeout=35):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl", "-sk", "--compressed", "-m", str(timeout), api],
                           capture_output=True, timeout=timeout + 5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

def next_data_from_html(h):
    m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None

def province_from(addr):
    a = addr or ""
    for p in S_PROVINCES:
        if p.replace(" ", "").lower() in a.replace(" ", "").lower():
            return "Phang Nga" if p == "Phangnga" else p
    return (a.split()[-1] if a.split() else "Thailand")

def area_sqm(lh):
    if not isinstance(lh, dict):
        return None
    tw = lh.get("squareWaInTotal") or lh.get("squareWa")
    if tw:
        return round(float(tw) * 4, 1)          # 1 talang wah = 4 m²
    rai = lh.get("rai") or 0; ngan = lh.get("ngan") or 0; wa = lh.get("squareWa") or 0
    total = rai * 1600 + ngan * 400 + wa * 4
    if total >= 40:
        return round(total, 1)
    ls = lh.get("landSize")
    if ls:
        return round(float(ls), 1)
    w, d = lh.get("width"), lh.get("depth")
    if w and d:
        return round(float(w) * float(d), 1)
    return None

def extract(listing):
    if listing.get("propertyType") != "LAND" or listing.get("postType") != "FOR_SALE":
        return None
    loc = listing.get("location") or {}
    lat, lng = loc.get("lat"), loc.get("lng")
    if lat is None or lng is None:
        return None
    if not (S_LAT[0] <= lat <= S_LAT[1] and S_LNG[0] <= lng <= S_LNG[1]):
        return None                               # outside the hunt area
    sale = ((listing.get("price") or {}).get("forSale") or {})
    thb = sale.get("price")
    if not thb:
        return None
    sqm = area_sqm(listing.get("landAndHouseInformation"))
    if not sqm or sqm < 40:
        return None
    slug = listing.get("slug"); lid = listing.get("id")
    if not slug or not lid:
        return None
    lh = listing.get("landAndHouseInformation") or {}
    rai = round(sqm / 1600, 2)
    return {
        "id": str(lid),
        "url": f"https://www.propertyhub.in.th/en/listings/{slug}---{lid}",
        "title": listing.get("title", "")[:200],
        "province": province_from(listing.get("address")),
        "locality": listing.get("address", ""),
        "sqm": sqm,
        "price_thb": int(thb),
        "price_usd": round(int(thb) / 36),
        "lat": round(float(lat), 6), "lng": round(float(lng), 6),
        "img": ("https://img.propertyhub.in.th" + listing["coverPicture"]) if listing.get("coverPicture") else "",
        "first_seen": (listing.get("createdAt") or "")[:10] or None,
        "rai_display": rai,
    }

def main():
    out = {}
    if os.path.exists(OUT):
        for r in json.load(open(OUT)):
            out[r["id"]] = r
    for slug in PROVINCE_SLUGS:
        h = via_relay(f"https://www.propertyhub.in.th/en/land-for-sale/{slug}")
        nd = next_data_from_html(h)
        if not nd:
            print(f"  {slug:>22}: no __NEXT_DATA__", file=sys.stderr)
            continue
        pp = nd["props"]["pageProps"]
        listings = pp.get("resultListings", [])
        total = (pp.get("pagination") or {}).get("totalCount")
        new = 0
        for L in listings:
            rec = extract(L)
            if rec and rec["id"] not in out:
                out[rec["id"]] = rec; new += 1
        note = " (fell back to all-TH → bbox-filtered)" if total == 6811 else f" of {total}"
        print(f"  {slug:>22}: {len(listings)} listings{note}, {new} new south-land (total {len(out)})", file=sys.stderr)
        json.dump(list(out.values()), open(OUT, "w"))
        time.sleep(0.4)

    json.dump(list(out.values()), open(OUT, "w"))
    print(f"TOTAL {len(out)} south-Thailand land rows -> {OUT}", file=sys.stderr)

if __name__ == "__main__":
    main()
