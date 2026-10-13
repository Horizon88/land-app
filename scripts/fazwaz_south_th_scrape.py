"""FazWaz Southern Thailand — land listings with distress detection.

List page: /land-for-sale/thailand/<province> — 30 listing URLs per page
Detail page has price/size/lat/lng/description/view.

Distress keywords scanned in title + description:
  urgent, quick sale, must sell, motivated seller, forced sale, distressed,
  reduced, price drop, price reduction, foreclosure, bank owned, below market,
  desperate, cash only, needs to sell, relocation, divorce sale, estate sale

Any hit → distress bump.
"""
import json, re, subprocess, sys, time, urllib.parse, os

RELAY = "https://landrelay.flag-theory.workers.dev"

# Southern Thailand provinces (coastal)
PROVINCES = [
    ("Phuket",      "phuket",       7.90,  98.36),
    ("Krabi",       "krabi",        8.06,  98.92),
    ("Phang Nga",   "phang-nga",    8.45,  98.53),
    ("Surat Thani", "surat-thani",  9.13,  99.33),
    ("Trang",       "trang",        7.56,  99.62),
    ("Songkhla",    "songkhla",     7.20, 100.60),
    ("Ranong",      "ranong",       9.97,  98.63),
    ("Chumphon",    "chumphon",    10.50,  99.18),
    ("Nakhon Si Thammarat", "nakhon-si-thammarat", 8.43, 99.96),
    ("Pattani",     "pattani",      6.87, 101.25),
    ("Satun",       "satun",        6.62, 100.07),
    # Islands typically shown as their own regions
    ("Koh Samui",   "koh-samui",    9.51, 100.02),
    ("Koh Phangan", "koh-phangan",  9.75, 100.03),
    ("Koh Lanta",   "koh-lanta",    7.63,  99.08),
    ("Koh Yao",     "koh-yao",      8.02,  98.60),
]

DISTRESS_PATS = [
    (r'\burgent(?:ly)?\b', 'urgent+15'),
    (r'\b(?:quick|fast)\s*sale\b', 'quick-sale+15'),
    (r'\bmust\s*sell\b', 'must-sell+18'),
    (r'\bmotivated\s*seller\b', 'motivated+18'),
    (r'\bforced\s*sale\b', 'forced-sale+30'),
    (r'\bdistressed?\b', 'distressed+25'),
    (r'\bprice\s*(?:drop|reduc|slash|cut)', 'price-drop+20'),
    (r'\breduced\s*(?:price|from|to)', 'reduced+15'),
    (r'\bforeclosure\b', 'foreclosure+30'),
    (r'\bbank[- ]owned\b', 'bank-owned+30'),
    (r'\bnpa\b', 'npa+25'),
    (r'\bnpl\b', 'npl+25'),
    (r'\bbelow\s*market\b', 'below-market+15'),
    (r'\bdesperate\b', 'desperate+20'),
    (r'\bcash\s*only\b', 'cash-only+10'),
    (r'\brelocation\b', 'relocation+10'),
    (r'\bdivorce\b', 'divorce+15'),
    (r'\bestate\s*sale\b', 'estate-sale+15'),
    (r'\bfire\s*sale\b', 'fire-sale+25'),
    (r'\bliquidation\b', 'liquidation+25'),
]

def via_relay(url, timeout=35):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

def parse_list_urls(body):
    """Return sorted list of unique detail URLs from search results."""
    return sorted(set(re.findall(r'href="(https?://www\.fazwaz\.com/property-sales/[^"]*-u\d+)"', body)))

def parse_detail(url, timeout=30):
    """Extract price, size, coords, description, distress markers."""
    body = via_relay(url, timeout)
    if not body or len(body) < 50000:
        return None
    # Title from <title>
    m_t = re.search(r'<title>([^<]+)</title>', body)
    title = m_t.group(1) if m_t else ""
    # Price from title format: "Land for Sale in Ao Nang, Krabi for $2,970,000 | U1990393"
    m_p = re.search(r'for\s*\$([\d,]+)', title)
    price = int(m_p.group(1).replace(",","")) if m_p else None
    # Size from body: "5,254 SqM" or "3.28 Rai"
    m_sqm = re.search(r'([\d,.]+)\s*SqM', body)
    sqm = None
    if m_sqm:
        try: sqm = float(m_sqm.group(1).replace(",",""))
        except: pass
    if not sqm:
        m_rai = re.search(r'([\d,.]+)\s*Rai\b', body, re.I)
        if m_rai:
            try: sqm = float(m_rai.group(1).replace(",","")) * 1600
            except: pass
    # Coords — lat="X" lng="Y"
    lat = lng = None
    m_c = re.search(r'lat="([-\d.]+)".{0,60}?lng="([-\d.]+)"', body, re.S)
    if m_c:
        try:
            la, lo = float(m_c.group(1)), float(m_c.group(2))
            if 5 < la < 21 and 95 < lo < 106:  # Thailand bounds
                lat, lng = la, lo
        except: pass
    # Description — search whole body for distress keywords
    text = body.lower()
    distress_hits = []
    distress_bonus = 0
    for pat, tag in DISTRESS_PATS:
        if re.search(pat, text):
            distress_hits.append(tag)
            distress_bonus += int(tag.rsplit("+",1)[1])
    # Cap distress bonus at 60 so a single listing doesn't dominate
    if distress_bonus > 60:
        distress_bonus = 60
    # Extract first image
    m_img = re.search(r'src="(https://cdn\.fazwaz\.com/[^"]+\.(?:jpg|jpeg|webp))', body)
    img = m_img.group(1) if m_img else ""
    return {
        "url": url,
        "id": url.rsplit("-u",1)[-1],
        "title": title[:160],
        "price_usd": price,
        "sqm": sqm,
        "lat": lat, "lng": lng,
        "img": img,
        "distress_hits": distress_hits,
        "distress_bonus": distress_bonus,
    }

if __name__ == "__main__":
    out_path = "/tmp/fazwaz_south.json"
    existing = {}
    if os.path.exists(out_path):
        for r in json.load(open(out_path)):
            existing[r["id"]] = r
        print(f"loaded {len(existing)} existing", file=sys.stderr)

    all_urls = []
    for prov_name, slug, lat0, lng0 in PROVINCES:
        seen = set()
        for page in range(1, 4):
            u = f"https://www.fazwaz.com/land-for-sale/thailand/{slug}"
            if page > 1: u += f"?page={page}"
            body = via_relay(u, timeout=30)
            if not body or len(body) < 30000: continue
            urls = parse_list_urls(body)
            new = [x for x in urls if x not in seen]
            for x in new: seen.add(x)
            all_urls.extend([(x, prov_name, lat0, lng0) for x in new])
            print(f"  {prov_name:>22} p{page}: {len(urls)} listings ({len(new)} new)", file=sys.stderr)
            if len(urls) < 15: break
            time.sleep(0.3)

    # Dedup by URL
    seen_urls = set(); dedup = []
    for tup in all_urls:
        if tup[0] in seen_urls: continue
        seen_urls.add(tup[0])
        dedup.append(tup)
    print(f"\ntotal unique urls: {len(dedup)}", file=sys.stderr)

    # Detail fetch (skip if already cached with real coords)
    results = []
    for i, (u, prov, lat0, lng0) in enumerate(dedup):
        lid = u.rsplit("-u",1)[-1]
        if lid in existing and existing[lid].get("lat") and existing[lid].get("price_usd"):
            r = existing[lid].copy()
            r["province"] = prov
            results.append(r)
            continue
        parsed = parse_detail(u, timeout=30)
        if not parsed:
            time.sleep(0.15)
            continue
        parsed["province"] = prov
        parsed["fb_lat"] = lat0
        parsed["fb_lng"] = lng0
        if not parsed["lat"]:
            parsed["lat"] = lat0; parsed["lng"] = lng0
        results.append(parsed)
        if i and i % 15 == 0:
            json.dump(results, open(out_path, "w"), ensure_ascii=False)
            n_dist = sum(1 for r in results if r.get("distress_bonus"))
            print(f"  detail {i}/{len(dedup)} (distressed so far: {n_dist})", file=sys.stderr)
        time.sleep(0.15)

    json.dump(results, open(out_path, "w"), ensure_ascii=False)
    n_p = sum(1 for r in results if r.get("price_usd"))
    n_ac = sum(1 for r in results if r.get("sqm"))
    n_c = sum(1 for r in results if r.get("lat") and r["lat"] != r.get("fb_lat"))
    n_d = sum(1 for r in results if r.get("distress_bonus"))
    print(f"\ndone. {len(results)} saved (price: {n_p}, sqm: {n_ac}, real coord: {n_c}, distressed: {n_d})", file=sys.stderr)
    from collections import Counter
    print(dict(Counter(r["province"] for r in results).most_common()), file=sys.stderr)
