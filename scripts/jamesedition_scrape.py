"""JamesEdition (luxury real estate marketplace) — Pacific sweep.

Card structure per listing:
  <a href="/real_estate/<location-slug>/<title-slug>-<id>" title="Title">
  ...
  <div class="ListingCard__price">$X,XXX</div>
  <div class="ListingCard__title">Actual name</div>
  <div class="ListingCard__location">Country/region</div>

No lat/lng in card. Detail page has coords via Google-Maps embed.
"""
import json, re, subprocess, sys, time, urllib.parse, os

RELAY = "https://landrelay.flag-theory.workers.dev"

COUNTRIES = [
    # (slug, name, friction, fb_lat, fb_lng)
    ("fiji",              "Fiji",              -20, -17.71, 178.06),
    ("french-polynesia",  "French Polynesia",  -15, -17.65,-149.42),
    ("tahiti",            "French Polynesia",  -15, -17.65,-149.42),
    ("vanuatu",           "Vanuatu",           -20, -15.38, 166.96),
    ("new-caledonia",     "New Caledonia",       0, -21.27, 165.63),
    ("cook-islands",      "Cook Islands",      -25, -21.24,-159.78),
    ("samoa",             "Samoa",               0, -13.75,-172.10),
    ("solomon-islands",   "Solomon Islands",   -25,  -9.65, 160.17),
    ("papua-new-guinea",  "Papua New Guinea",  -20,  -6.31, 143.96),
    ("palau",             "Palau",             -15,   7.51, 134.58),
    ("tonga",             "Tonga",             -30, -21.18,-175.20),
    ("marshall-islands",  "Marshall Islands",  -15,   7.13, 171.18),
    ("micronesia",        "Micronesia",        -20,   6.92, 158.19),
    ("kiribati",          "Kiribati",          -25,   1.42, 172.98),
    # Bonus: countries adjacent that JE indexes but we skipped realtor.com
    ("new-zealand-region","New Zealand",       -25, -41.29, 174.78),
    ("australia",         "Australia",         -10, -25.27, 133.78),
]

FOREIGN_NOTES = {
    "Fiji":              "Fiji: mostly native lease (99-year); freehold rare and iTaukei consent required for coastal.",
    "French Polynesia":  "Tahiti: freehold available for non-French but permit process complex.",
    "Vanuatu":           "Vanuatu: NO freehold for non-citizens; 75-year lease max.",
    "New Caledonia":     "French territory: freehold available for anyone.",
    "Cook Islands":      "Foreign lease-only (60-year); freehold reserved for Cook Islanders.",
    "Samoa":             "Freehold on non-customary land OK for foreigners.",
    "Solomon Islands":   "Foreign lease-only; customary land dominates.",
    "Papua New Guinea":  "99-year state lease max for foreigners.",
    "Palau":             "Lease-only for foreigners (99-yr).",
    "Tonga":             "NO foreign land ownership; 20-year lease max via Tongan owner.",
    "Marshall Islands":  "Long-term lease common; no freehold for foreigners.",
    "Micronesia":        "Lease-only; complex land tenure per state.",
    "Kiribati":          "Foreign lease-only; land is scarce and customary.",
    "New Zealand":       "OIA blocks residential; rural land needs OIO consent.",
    "Australia":         "FIRB approval required for non-resident purchases.",
}

def via_relay(url, timeout=45):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

CARD_HREF = re.compile(r'href="(/real_estate/[a-z0-9-]+/[^"]+-(\d+))"[^>]*title="([^"]+)"')
PRICE_NEAR = re.compile(r'ListingCard__price">\s*\$([\d,]+)')
LOC_NEAR = re.compile(r'ListingCard__location">\s*([^<]+?)\s*<')
IMG_NEAR = re.compile(r'src="(https://img\.jamesedition\.com/[^"]+\.jpg)"')

def parse_list(body):
    rows = []
    seen = set()
    for m in CARD_HREF.finditer(body):
        u, lid, title = m.group(1), m.group(2), m.group(3)
        if lid in seen: continue
        seen.add(lid)
        ctx = body[m.start():m.start()+8000]
        m_p = PRICE_NEAR.search(ctx)
        m_l = LOC_NEAR.search(ctx)
        m_i = IMG_NEAR.search(ctx)
        if not m_p: continue
        try: price = int(m_p.group(1).replace(",",""))
        except: continue
        rows.append({
            "id": lid,
            "url": "https://www.jamesedition.com" + u,
            "title": title[:140],
            "price_usd": price,
            "loc": (m_l.group(1).strip() if m_l else "")[:80],
            "img": m_i.group(1) if m_i else "",
        })
    return rows

def fetch_detail(url, timeout=25):
    body = via_relay(url, timeout)
    if not body or len(body) < 30000:
        return None, None, None
    lat = lng = None
    # JE detail often has Google-Maps center or a data-lat attribute
    m = re.search(r'"latitude"\s*:\s*"?([-\d.]+).{0,80}?"longitude"\s*:\s*"?([-\d.]+)', body, re.S) \
        or re.search(r'data-lat="([-\d.]+)".{0,80}?data-lng="([-\d.]+)"', body, re.S) \
        or re.search(r'/maps[^"]*?[?&]q=([-\d.]+),([-\d.]+)', body)
    if m:
        try:
            la, lo = float(m.group(1)), float(m.group(2))
            if -60 < la < 60 and -180 < lo < 180:
                lat, lng = la, lo
        except: pass
    # Land area (acres or sqft)
    ac = None
    m_ac = re.search(r'([\d.,]+)\s*acres?', body, re.I)
    if m_ac:
        try: ac = float(m_ac.group(1).replace(",",""))
        except: pass
    if not ac:
        m_ha = re.search(r'([\d.,]+)\s*hectares?', body, re.I)
        if m_ha:
            try: ac = float(m_ha.group(1).replace(",","")) * 2.47105
            except: pass
    return lat, lng, ac

if __name__ == "__main__":
    out_path = "/tmp/jamesedition_pacific.json"
    existing = {}
    if os.path.exists(out_path):
        for r in json.load(open(out_path)):
            existing[r["id"]] = r
        print(f"loaded {len(existing)} existing", file=sys.stderr)

    all_rows = []
    for slug, country, ff, lat0, lng0 in COUNTRIES:
        for page in range(1, 8):
            url = f"https://www.jamesedition.com/real_estate/{slug}"
            if page > 1: url += f"?page={page}"
            body = via_relay(url, timeout=35)
            if not body or len(body) < 30000: continue
            rows = parse_list(body)
            if not rows: break
            for r in rows:
                r["country"] = country
                r["slug"] = slug
                r["foreign_friction"] = ff
                r["foreign_note"] = FOREIGN_NOTES.get(country, "")
                r["fb_lat"] = lat0
                r["fb_lng"] = lng0
            new = sum(1 for r in rows if r["id"] not in {x["id"] for x in all_rows})
            all_rows.extend(rows)
            print(f"  {country:>20} p{page}: {len(rows)} (+{new} unique)", file=sys.stderr)
            time.sleep(0.3)
            if len(rows) < 10: break

    seen = set(); deduped = []
    for r in all_rows:
        if r["id"] in seen: continue
        seen.add(r["id"])
        deduped.append(r)
    print(f"\ntotal unique: {len(deduped)}", file=sys.stderr)

    for i, r in enumerate(deduped):
        cached = existing.get(r["id"])
        if cached and cached.get("lat") and cached["lat"] != r["fb_lat"]:
            r["lat"] = cached["lat"]; r["lng"] = cached["lng"]
            r["acres"] = cached.get("acres")
            continue
        lat, lng, ac = fetch_detail(r["url"], timeout=25)
        r["lat"] = lat or r["fb_lat"]
        r["lng"] = lng or r["fb_lng"]
        r["acres"] = ac
        if i and i % 20 == 0:
            json.dump(deduped, open(out_path, "w"), ensure_ascii=False)
            print(f"  detail {i}/{len(deduped)}", file=sys.stderr)
        time.sleep(0.2)

    json.dump(deduped, open(out_path, "w"), ensure_ascii=False)
    from collections import Counter
    n_ac = sum(1 for r in deduped if r.get("acres"))
    n_real = sum(1 for r in deduped if r.get("lat") and r["lat"] != r["fb_lat"])
    print(f"\ndone. {len(deduped)} saved (real coords: {n_real}, with acres: {n_ac})", file=sys.stderr)
    print(dict(Counter(r["country"] for r in deduped).most_common()), file=sys.stderr)
