"""Realtor.com International — Pacific island land/home sweep.

Country slugs (ISO2 lowercase):
  fj - Fiji
  pf - French Polynesia (Tahiti)
  vu - Vanuatu
  nc - New Caledonia
  ws - Samoa
  to - Tonga
  ck - Cook Islands
  pg - Papua New Guinea
  sb - Solomon Islands
  pw - Palau
  ki - Kiribati
  fm - Micronesia
  mh - Marshall Islands
  nr - Nauru
  tv - Tuvalu
  nu - Niue

List page returns ~25-37 listings per URL. Detail pages have lat/lng + full
area. Currency varies: USD is common on the international portal.

Foreign friction per country:
  FJ  -20 : freehold rare; 99-year native lease common
  PF  -15 : freehold OK for non-French but complex
  VU  -20 : 75-year lease max (no freehold for foreigners)
  WS   +0 : freehold OK for foreigners in customary-land-freed zones
  TO  -30 : NO land ownership by foreigners (lease only, 20yr)
  CK  -25 : Cook Islanders only own land; foreigners lease
  NC   +0 : French-territory; freehold OK
  PG  -20 : 99-year state lease max
  SB  -25 : lease only for foreigners
  PW  -15 : lease-only for foreigners
"""
import json, re, subprocess, sys, time, urllib.parse, os

RELAY = "https://landrelay.flag-theory.workers.dev"

COUNTRIES = [
    # (code, country_name, foreign_friction, foreign_note, fallback_lat, fallback_lng)
    ("fj", "Fiji",              -20, "Fiji: mostly native lease (99-year); freehold rare and coastal iTaukei consent required.",       -17.71, 178.06),
    ("pf", "French Polynesia",  -15, "Tahiti: freehold available for non-French but permit process complex; ROI limits on flipping.",  -17.65,-149.42),
    ("vu", "Vanuatu",           -20, "Vanuatu: NO freehold for non-citizens; 75-year lease max.",                                       -15.38, 166.96),
    ("nc", "New Caledonia",      0, "French territory: freehold available for anyone; Nouméa taxes apply.",                             -21.27, 165.63),
    ("ws", "Samoa",              0, "Samoa: freehold on non-customary land OK for foreigners.",                                        -13.75,-172.10),
    ("to", "Tonga",             -30, "Tonga: NO foreign land ownership; 20-year lease max via Tongan owner.",                          -21.18,-175.20),
    ("ck", "Cook Islands",      -25, "Cook Islands: foreign lease-only (60-year max); freehold reserved for Cook Islanders.",          -21.24,-159.78),
    ("pg", "Papua New Guinea",  -20, "PNG: 99-year state lease max for foreigners; customary land 97% not open.",                       -6.31, 143.96),
    ("sb", "Solomon Islands",   -25, "Solomon: foreign lease-only; customary land dominates.",                                          -9.65, 160.17),
    ("pw", "Palau",             -15, "Palau: lease-only for foreigners (99-yr).",                                                        7.51, 134.58),
]

def via_relay(url, timeout=45):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

def parse_list(body):
    """Extract listings from /international/<cc>/ result page."""
    rows = []
    seen = set()
    for m in re.finditer(r'href="(/international/[a-z]{2}/[^"]+)"', body):
        u = m.group(1)
        if u in seen: continue
        # Skip category links
        if not re.search(r'-\d{9,}/', u): continue  # listing IDs are long numbers
        seen.add(u)
        ctx = body[m.start():m.start()+2500]
        m_price = re.search(r'\$([\d,]{4,})', ctx)
        m_type = re.search(r'data-testid="property-type"[^>]*>([^<]+)</', ctx)
        m_addr = re.search(r'data-testid="address"[^>]*>([^<]+)</', ctx)
        m_img = re.search(r'src="(https://[^"]+\.(?:jpg|jpeg|png|webp))', ctx, re.I)
        if not m_price: continue
        try: price = int(m_price.group(1).replace(",",""))
        except: continue
        rows.append({
            "id": u.rsplit("-",1)[-1].strip("/"),
            "url": "https://www.realtor.com" + u,
            "price_usd": price,
            "type": (m_type.group(1).strip() if m_type else "").lower(),
            "addr": (m_addr.group(1).strip() if m_addr else ""),
            "img": (m_img.group(1) if m_img else ""),
        })
    return rows

def fetch_detail(url, timeout=25):
    """Return (lat, lng, sqft_or_sqm, land_size_ac) from a detail page."""
    body = via_relay(url, timeout)
    if not body or len(body) < 40000:
        return None, None, None, None
    lat = lng = None
    m = re.search(r'"latitude"\s*:\s*"?([-\d.]+).{0,80}?"longitude"\s*:\s*"?([-\d.]+)', body, re.S)
    if m:
        try: lat, lng = float(m.group(1)), float(m.group(2))
        except: pass
    # Interior size (sqft or sqm)
    sqft = None
    m_sqft = re.search(r'([\d,]+)\s*(?:sqft|sq\s*ft|square\s*feet)', body, re.I)
    if m_sqft:
        try: sqft = int(m_sqft.group(1).replace(",",""))
        except: pass
    m_sqm = re.search(r'([\d,]+)\s*(?:sqm|m²|square\s*meters?)', body, re.I)
    if m_sqm and not sqft:
        try:
            n = int(m_sqm.group(1).replace(",",""))
            sqft = int(n * 10.7639)   # sqm → sqft
        except: pass
    # Land size (acres)
    ac = None
    m_ac = re.search(r'([\d.,]+)\s*acres?', body, re.I)
    if m_ac:
        try: ac = float(m_ac.group(1).replace(",",""))
        except: pass
    m_ha = re.search(r'([\d.,]+)\s*hectares?', body, re.I)
    if m_ha and not ac:
        try: ac = float(m_ha.group(1).replace(",","")) * 2.47105
        except: pass
    return lat, lng, sqft, ac

if __name__ == "__main__":
    out_path = "/tmp/realtor_pacific.json"
    existing = {}
    if os.path.exists(out_path):
        for r in json.load(open(out_path)):
            existing[r["id"]] = r
        print(f"loaded {len(existing)} existing", file=sys.stderr)

    all_rows = []
    for cc, cname, ff, note, lat0, lng0 in COUNTRIES:
        for page in range(1, 8):
            url = f"https://www.realtor.com/international/{cc}/"
            if page > 1: url += f"page-{page}/"
            body = via_relay(url, timeout=35)
            if not body or len(body) < 30000: continue
            rows = parse_list(body)
            if not rows: break
            for r in rows:
                r["country"] = cname
                r["cc"] = cc
                r["foreign_friction"] = ff
                r["foreign_note"] = note
                r["fb_lat"] = lat0
                r["fb_lng"] = lng0
            new = sum(1 for r in rows if r["id"] not in {x["id"] for x in all_rows})
            all_rows.extend(rows)
            print(f"  {cname:>18} p{page}: {len(rows)} (+{new} unique)", file=sys.stderr)
            time.sleep(0.3)
            if len(rows) < 15: break  # partial page = last

    # Dedup
    seen = set(); deduped = []
    for r in all_rows:
        if r["id"] in seen: continue
        seen.add(r["id"])
        deduped.append(r)
    print(f"\ntotal unique: {len(deduped)}", file=sys.stderr)

    # Phase 2: detail-fetch
    for i, r in enumerate(deduped):
        cached = existing.get(r["id"])
        if cached and cached.get("lat") and cached.get("lat") != r["fb_lat"]:
            r["lat"] = cached["lat"]; r["lng"] = cached["lng"]
            r["sqft"] = cached.get("sqft"); r["acres"] = cached.get("acres")
            continue
        lat, lng, sqft, ac = fetch_detail(r["url"], timeout=25)
        r["lat"] = lat or r["fb_lat"]
        r["lng"] = lng or r["fb_lng"]
        r["sqft"] = sqft
        r["acres"] = ac
        if i and i % 20 == 0:
            json.dump(deduped, open(out_path, "w"), ensure_ascii=False)
            print(f"  detail {i}/{len(deduped)}", file=sys.stderr)
        time.sleep(0.2)

    json.dump(deduped, open(out_path, "w"), ensure_ascii=False)
    n_real = sum(1 for r in deduped if r.get("lat") and r["lat"] != r["fb_lat"])
    n_ac = sum(1 for r in deduped if r.get("acres"))
    print(f"\ndone. {len(deduped)} saved (real coords: {n_real}, with acres: {n_ac})", file=sys.stderr)
    from collections import Counter
    print(dict(Counter(r["country"] for r in deduped).most_common()), file=sys.stderr)
