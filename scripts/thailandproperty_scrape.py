"""thailand-property.com (English, farang-facing) — land scrape.

Same PropertyGuru-group backend as DotProperty (identical /ads/ URL shape),
but the list page does NOT embed a clean ItemList JSON-LD, so we:
  1. scrape LIST pages -> collect /ads/land-for-sale-in-...  detail URLs
  2. fetch each DETAIL page -> price (JSON-LD Offer, THB), land area
     ("Land area: N m2"), coords (<meta itemprop="latitude/longitude">),
     name, locality/province (from the URL slug).

Heavily syndicates FazWaz, so the merge dedups against existing inventory
by coords+price. Emits /tmp/thailandproperty.json for the merge step.

Bounded for cron use: MAX_PAGES/province and DETAIL_CAP/run keep runtime in
check; a resume cache means repeat runs only fetch details not seen before.
"""
import json, re, subprocess, sys, time, urllib.parse, os

RELAY = "https://landrelay.flag-theory.workers.dev"
BASE = "https://www.thailand-property.com"

# South-Thailand hunt provinces (thailand-property province slugs)
PROVINCES = ["phuket", "krabi", "phang-nga", "surat-thani", "trang",
             "nakhon-si-thammarat", "chumphon", "ranong", "satun",
             "prachuap-khiri-khan", "songkhla"]
MAX_PAGES = 15          # ~30 listings/page
DETAIL_CAP = 500        # max detail fetches per run (cron budget guard)
OUT = "/tmp/thailandproperty.json"

def via_relay(url, timeout=35):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl", "-sk", "--compressed", "-m", str(timeout), api],
                           capture_output=True, timeout=timeout + 5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

AD_RE = re.compile(r'href="(https://www\.thailand-property\.com/ads/land-for-sale-in-[^"]+)"')

def list_urls(prov, page):
    u = f"{BASE}/land-for-sale/{prov}" + (f"?page={page}" if page > 1 else "")
    h = via_relay(u)
    return list(dict.fromkeys(AD_RE.findall(h)))

def num(s):
    try: return float(str(s).replace(",", ""))
    except Exception: return None

def parse_detail(url):
    h = via_relay(url)
    if not h or len(h) < 5000:
        return None
    # price: JSON-LD Offer (THB), take the largest 5+ digit price seen
    prices = [int(x) for x in re.findall(r'"price"\s*:\s*"?(\d{5,})"?', h)]
    thb = max(prices) if prices else None
    # land area in m2
    m = re.search(r'Land area:\s*([\d,]+)\s*m', h, re.I)
    sqm = num(m.group(1)) if m else None
    if not sqm:  # fallback: rai in "/ N Rai"
        r = re.search(r'([\d,.]+)\s*Rai', h)
        if r:
            v = num(r.group(1))
            if v: sqm = v * 1600
    # coords from itemprop meta
    lat = re.search(r'itemprop="latitude"[^>]*content="([-\d.]+)"', h)
    lng = re.search(r'itemprop="longitude"[^>]*content="([-\d.]+)"', h)
    lat = num(lat.group(1)) if lat else None
    lng = num(lng.group(1)) if lng else None
    # name
    nm = re.search(r'<script[^>]*application/ld\+json[^>]*>.*?"name"\s*:\s*"([^"]+)"', h, re.S)
    name = nm.group(1) if nm else ""
    # locality/province from url slug: land-for-sale-in-<locality>-<province>_<id>
    slug = re.search(r'/ads/land-for-sale-in-(.+?)_[0-9a-f]', url)
    locality, province = "", ""
    if slug:
        parts = slug.group(1).split("-")
        province = parts[-1].replace("-", " ").title() if parts else ""
        locality = " ".join(parts[:-1]).title()
    return {"url": url, "price_thb": thb, "sqm": sqm, "lat": lat, "lng": lng,
            "name": name[:180], "locality": locality, "province": province}

if __name__ == "__main__":
    out = {}
    if os.path.exists(OUT):
        for r in json.load(open(OUT)):
            out[r["url"]] = r

    # 1. gather candidate detail URLs from list pages
    todo = []
    for prov in PROVINCES:
        got = 0
        for page in range(1, MAX_PAGES + 1):
            urls = list_urls(prov, page)
            if not urls:
                break
            fresh = [u for u in urls if u not in out]
            todo.extend(fresh); got += len(fresh)
            print(f"  list {prov:>20} p{page}: {len(urls)} urls, {len(fresh)} new", file=sys.stderr)
            if not fresh:
                break
            time.sleep(0.3)
        print(f"{prov}: {got} candidate urls", file=sys.stderr)
    todo = list(dict.fromkeys(todo))
    print(f"TOTAL candidates to fetch: {len(todo)} (cap {DETAIL_CAP})", file=sys.stderr)

    # 2. fetch details (bounded)
    n = 0
    for url in todo[:DETAIL_CAP]:
        rec = parse_detail(url)
        n += 1
        if rec and rec.get("price_thb") and rec.get("sqm"):
            out[url] = rec
        if n % 25 == 0:
            json.dump(list(out.values()), open(OUT, "w"))
            print(f"  detail {n}/{min(len(todo), DETAIL_CAP)} · saved {len(out)}", file=sys.stderr)
        time.sleep(0.25)

    json.dump(list(out.values()), open(OUT, "w"))
    sized = sum(1 for r in out.values() if r.get("sqm"))
    coord = sum(1 for r in out.values() if r.get("lat"))
    print(f"TOTAL {len(out)} ({sized} sized, {coord} coord) -> {OUT}", file=sys.stderr)
