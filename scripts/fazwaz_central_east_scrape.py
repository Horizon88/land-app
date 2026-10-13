"""FazWaz Central/Eastern Thailand coast — land listings with distress detection.

Adds the missing Thai coastal provinces we don't have in the earlier
Southern scrape: Chonburi (Pattaya + Sattahip), Rayong, Chanthaburi,
Trat (Koh Chang / Koh Kood), Petchaburi (Cha-am), Prachuap Khiri Khan
(Hua Hin), plus Samut Songkhram / Samut Sakhon for the Bangkok-side
Gulf coast.

Same detail-page parser + distress-keyword scan as the Southern scraper.
"""
import json, re, subprocess, sys, time, urllib.parse, os

RELAY = "https://landrelay.flag-theory.workers.dev"

PROVINCES = [
    # Central Gulf coast
    ("Chonburi",             "chonburi",              13.36, 100.98),
    ("Pattaya",              "pattaya",               12.92, 100.88),
    ("Sattahip",             "sattahip",              12.66, 100.90),
    # Eastern Gulf coast
    ("Rayong",               "rayong",                12.68, 101.28),
    ("Chanthaburi",          "chanthaburi",           12.61, 102.10),
    ("Trat",                 "trat",                  12.24, 102.51),
    ("Koh Chang (Trat)",     "koh-chang",             12.05, 102.35),
    ("Koh Kood",             "koh-kood",              11.65, 102.55),
    # Western Gulf coast
    ("Petchaburi",           "petchaburi",            13.11,  99.94),
    ("Cha-am",               "cha-am",                12.80,  99.97),
    ("Prachuap Khiri Khan",  "prachuap-khiri-khan",   11.81,  99.79),
    ("Hua Hin",              "hua-hin",               12.57,  99.96),
    # Bangkok-area coast
    ("Samut Songkhram",      "samut-songkhram",       13.42, 100.00),
    ("Samut Sakhon",         "samut-sakhon",          13.55, 100.27),
    ("Samut Prakan",         "samut-prakan",          13.60, 100.60),
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
    return sorted(set(re.findall(r'href="(https?://www\.fazwaz\.com/property-sales/[^"]*-u\d+)"', body)))

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
    if not sqm:
        m_rai = re.search(r'([\d,.]+)\s*Rai\b', body, re.I)
        if m_rai:
            try: sqm = float(m_rai.group(1).replace(",","")) * 1600
            except: pass
    lat = lng = None
    m_c = re.search(r'lat="([-\d.]+)".{0,60}?lng="([-\d.]+)"', body, re.S)
    if m_c:
        try:
            la, lo = float(m_c.group(1)), float(m_c.group(2))
            if 5 < la < 21 and 95 < lo < 106:
                lat, lng = la, lo
        except: pass
    text = body.lower()
    distress_hits = []
    distress_bonus = 0
    for pat, tag in DISTRESS_PATS:
        if re.search(pat, text):
            distress_hits.append(tag)
            distress_bonus += int(tag.rsplit("+",1)[1])
    if distress_bonus > 60: distress_bonus = 60
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
    out_path = "/tmp/fazwaz_central_east.json"
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

    seen_urls = set(); dedup = []
    for tup in all_urls:
        if tup[0] in seen_urls: continue
        seen_urls.add(tup[0]); dedup.append(tup)
    print(f"\ntotal unique urls: {len(dedup)}", file=sys.stderr)

    results = []
    for i, (u, prov, lat0, lng0) in enumerate(dedup):
        lid = u.rsplit("-u",1)[-1]
        if lid in existing and existing[lid].get("lat") and existing[lid].get("price_usd"):
            r = existing[lid].copy(); r["province"] = prov; results.append(r); continue
        parsed = parse_detail(u, timeout=30)
        if not parsed: time.sleep(0.15); continue
        parsed["province"] = prov; parsed["fb_lat"] = lat0; parsed["fb_lng"] = lng0
        if not parsed["lat"]: parsed["lat"] = lat0; parsed["lng"] = lng0
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
