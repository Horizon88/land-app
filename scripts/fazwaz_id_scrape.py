"""FazWaz Indonesia — land listings (Bali / Lombok / Yogyakarta).

Same relay + parse pattern as fazwaz_south_th_scrape.py; fazwaz.id detail
pages carry USD price in the <title>, SqM size, lat/lng attrs, cdn images.

Emits /tmp/fazwaz_id.json for fazwaz_id_merge.py.
"""
import json, re, subprocess, sys, time, urllib.parse, os

RELAY = "https://landrelay.flag-theory.workers.dev"

# (region display, url slug, pages to walk, fallback lat/lng)
REGIONS = [
    ("Bali",       "bali",       12, -8.4,  115.2),
    ("Lombok",     "lombok",      5, -8.65, 116.32),
    ("Yogyakarta", "yogyakarta",  4, -7.80, 110.36),
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
    (r'\bbelow\s*market\b', 'below-market+15'),
    (r'\bcash\s*only\b', 'cash-only+10'),
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
    return sorted(set(re.findall(r'href="(https://www\.fazwaz\.id/property-sales/[^"]*-u\d+)"', body)))

def parse_detail(url, timeout=30):
    body = via_relay(url, timeout)
    if not body or len(body) < 50000:
        return None
    m_t = re.search(r'<title>([^<]+)</title>', body)
    title = m_t.group(1) if m_t else ""
    m_p = re.search(r'for\s*\$([\d,]+)', title)
    price = int(m_p.group(1).replace(",","")) if m_p else None
    m_sqm = re.search(r'([\d,.]+)\s*SqM', body)
    sqm = None
    if m_sqm:
        try: sqm = float(m_sqm.group(1).replace(",",""))
        except: pass
    lat = lng = None
    m_c = re.search(r'lat="([-\d.]+)".{0,60}?lng="([-\d.]+)"', body, re.S)
    if m_c:
        try:
            la, lo = float(m_c.group(1)), float(m_c.group(2))
            if -11 < la < 6 and 95 < lo < 141:  # Indonesia bounds
                lat, lng = la, lo
        except: pass
    text = body.lower()
    hits, bonus = [], 0
    for pat, tag in DISTRESS_PATS:
        if re.search(pat, text):
            hits.append(tag); bonus += int(tag.rsplit("+",1)[1])
    bonus = min(bonus, 60)
    m_img = re.search(r'src="(https://cdn\.fazwaz\.com/[^"]+\.(?:jpg|jpeg|webp))', body)
    # area from title: "Land for Sale in Sidemen, Bali for ..."
    m_a = re.search(r'in\s+([^,|]+),', title)
    return {
        "url": url, "id": url.rsplit("-u",1)[-1],
        "title": title[:160], "area_name": (m_a.group(1).strip() if m_a else "")[:40],
        "price_usd": price, "sqm": sqm, "lat": lat, "lng": lng,
        "img": m_img.group(1) if m_img else "",
        "distress_hits": hits, "distress_bonus": bonus,
    }

if __name__ == "__main__":
    out_path = "/tmp/fazwaz_id.json"
    existing = {}
    if os.path.exists(out_path):
        for r in json.load(open(out_path)):
            existing[r["id"]] = r
        print(f"loaded {len(existing)} existing", file=sys.stderr)

    all_urls = []
    for region, slug, max_pg, lat0, lng0 in REGIONS:
        seen = set()
        for page in range(1, max_pg + 1):
            u = f"https://www.fazwaz.id/land-for-sale/indonesia/{slug}"
            if page > 1: u += f"?page={page}"
            body = via_relay(u, timeout=30)
            if not body or len(body) < 30000: continue
            urls = parse_list_urls(body)
            new = [x for x in urls if x not in seen]
            for x in new: seen.add(x)
            all_urls.extend([(x, region, lat0, lng0) for x in new])
            print(f"  {region:>12} p{page}: {len(urls)} listings ({len(new)} new)", file=sys.stderr)
            if len(new) == 0: break
            time.sleep(0.3)

    seen_urls = set(); dedup = []
    for tup in all_urls:
        if tup[0] in seen_urls: continue
        seen_urls.add(tup[0]); dedup.append(tup)
    print(f"\ntotal unique urls: {len(dedup)}", file=sys.stderr)

    results = []
    for i, (u, region, lat0, lng0) in enumerate(dedup):
        lid = u.rsplit("-u",1)[-1]
        if lid in existing and existing[lid].get("lat") and existing[lid].get("price_usd"):
            r = existing[lid].copy(); r["region"] = region
            results.append(r); continue
        parsed = parse_detail(u, timeout=30)
        if not parsed:
            time.sleep(0.15); continue
        parsed["region"] = region
        if not parsed.get("lat"):
            parsed["lat"], parsed["lng"] = lat0, lng0
        results.append(parsed)
        if (i+1) % 20 == 0:
            print(f"  detail {i+1}/{len(dedup)} ({len(results)} ok)", file=sys.stderr)
            json.dump(results, open(out_path, "w"))
        time.sleep(0.2)

    json.dump(results, open(out_path, "w"))
    print(f"DONE {len(results)} rows -> {out_path}", file=sys.stderr)
