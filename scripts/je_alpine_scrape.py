"""JamesEdition Alpine mountain-homes scrape — Switzerland, Austria, Georgia.

Filters to MOUNTAIN properties only:
  - resort/village slug is on our curated ski-town list, or
  - title/location mentions mountain/ski/alp/valley/summit/chalet keywords

Emits chalet / villa / mountain-home listings with lat/lng resolved from
detail page (JamesEdition includes maps center).
"""
import json, re, subprocess, sys, time, urllib.parse, os

RELAY = "https://landrelay.flag-theory.workers.dev"

# Slug list = country + specific ski towns
SEARCHES = [
    # Switzerland — country + resorts
    ("Switzerland", "switzerland",              -12, 46.80,   8.20),
    ("Switzerland", "verbier-switzerland",      -12, 46.10,   7.23),
    ("Switzerland", "zermatt-switzerland",      -12, 46.02,   7.75),
    ("Switzerland", "st-moritz-switzerland",    -12, 46.50,   9.84),
    ("Switzerland", "gstaad-switzerland",       -12, 46.47,   7.29),
    ("Switzerland", "davos-switzerland",        -12, 46.80,   9.83),
    ("Switzerland", "crans-montana-switzerland",-12, 46.31,   7.48),
    ("Switzerland", "villars-switzerland",      -12, 46.30,   7.05),
    ("Switzerland", "grindelwald-switzerland",  -12, 46.62,   8.03),
    ("Switzerland", "wengen-switzerland",       -12, 46.61,   7.92),
    ("Switzerland", "andermatt-switzerland",    -12, 46.63,   8.60),
    ("Switzerland", "engadin-switzerland",      -12, 46.50,   9.84),
    # Austria — country + resorts
    ("Austria",     "austria",                  -12, 47.60,  13.90),
    ("Austria",     "kitzbuhel-austria",        -12, 47.45,  12.39),
    ("Austria",     "lech-austria",             -12, 47.21,  10.14),
    ("Austria",     "sankt-anton-austria",      -12, 47.13,  10.27),
    ("Austria",     "tirol-austria",            -12, 47.25,  11.40),
    ("Austria",     "salzburg-austria",         -12, 47.80,  13.05),
    ("Austria",     "zell-am-see-austria",      -12, 47.33,  12.79),
    ("Austria",     "solden-austria",           -12, 46.97,  11.00),
    ("Austria",     "ischgl-austria",           -12, 47.01,  10.29),
    ("Austria",     "mayrhofen-austria",        -12, 47.17,  11.87),
    # Georgia
    ("Georgia",     "georgia-country",           -8, 42.31,  43.36),
    ("Georgia",     "gudauri-georgia",           -8, 42.47,  44.48),
    ("Georgia",     "bakuriani-georgia",         -8, 41.75,  43.53),
    ("Georgia",     "kazbegi-georgia",           -8, 42.66,  44.64),
    ("Georgia",     "svaneti-georgia",           -8, 42.92,  42.73),
    ("Georgia",     "mestia-georgia",            -8, 43.05,  42.72),
    ("Georgia",     "tbilisi-georgia",           -8, 41.72,  44.79),
]

FOREIGN_NOTES = {
    "Switzerland": "CH: non-residents restricted by Lex Koller. Alpine resort communes have annual foreign-purchase quotas (mostly filled). Buy via commercial (chalet-hotel operator) or holiday-home authorization.",
    "Austria":     "AT: non-EU buyers need Ausländergrunderwerbsgesetz permit per state. Vorarlberg + Tirol very restrictive; Kärnten more open. Tourist-zone chalets often easier.",
    "Georgia":     "GE: foreigners can hold urban land freehold. Agricultural land (>5ha) restricted to Georgian citizens — mountain plots often OK if <5ha.",
}

CARD = re.compile(r'href="(/real_estate/[a-z0-9-]+/[^"]+-(\d+))"[^>]*title="([^"]+)"')
PRICE = re.compile(r'ListingCard__price">\s*([€$£¥₾CHF]+|USD|EUR|CHF|GEL)?\s*([\d,.]+)')
LOC = re.compile(r'ListingCard__location">\s*([^<]+?)\s*<')
IMG = re.compile(r'src="(https://img\.jamesedition\.com/[^"]+\.jpg)"')

# Detect mountain / ski / chalet signal in title or slug
MTN_RE = re.compile(r'chalet|ski|alp|mountain|summit|valley|mont|berg|hütte|alm|piste|slope|resort|village|lodge|refuge|panorama', re.I)

def via_relay(url, timeout=45):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

def parse_list(body, slug_is_resort):
    rows = []
    seen = set()
    for m in CARD.finditer(body):
        u, lid, title = m.group(1), m.group(2), m.group(3)
        if lid in seen: continue
        seen.add(lid)
        ctx = body[m.start():m.start()+8000]
        m_p = PRICE.search(ctx)
        m_l = LOC.search(ctx)
        m_i = IMG.search(ctx)
        if not m_p: continue
        currency = (m_p.group(1) or "").strip()
        try: price = float(m_p.group(2).replace(",",""))
        except: continue
        loc = (m_l.group(1).strip() if m_l else "")
        # Filter: keep if slug is a resort OR title/loc has mountain keyword
        text = title + " " + loc
        if not (slug_is_resort or MTN_RE.search(text)): continue
        rows.append({
            "id": lid,
            "url": "https://www.jamesedition.com" + u,
            "title": title[:180],
            "loc": loc[:100],
            "currency": currency,
            "price_native": price,
            "img": m_i.group(1) if m_i else "",
        })
    return rows

def fetch_detail(url, timeout=25):
    body = via_relay(url, timeout)
    if not body or len(body) < 30000:
        return None, None, None
    lat = lng = None
    m = re.search(r'"latitude"\s*:\s*"?([-\d.]+).{0,80}?"longitude"\s*:\s*"?([-\d.]+)', body, re.S) \
        or re.search(r'data-lat="([-\d.]+)".{0,80}?data-lng="([-\d.]+)"', body, re.S) \
        or re.search(r'/maps[^"]*?[?&]q=([-\d.]+),([-\d.]+)', body)
    if m:
        try:
            la, lo = float(m.group(1)), float(m.group(2))
            if -60 < la < 70 and -180 < lo < 180: lat, lng = la, lo
        except: pass
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
    out_path = "/tmp/je_alpine.json"
    existing = {}
    if os.path.exists(out_path):
        for r in json.load(open(out_path)):
            existing[r["id"]] = r
        print(f"loaded {len(existing)} existing", file=sys.stderr)

    all_rows = []
    for country, slug, ff, lat0, lng0 in SEARCHES:
        slug_is_resort = "-" in slug and not slug.endswith("-country") and slug not in ("switzerland","austria")
        for page in range(1, 5):
            url = f"https://www.jamesedition.com/real_estate/{slug}"
            if page > 1: url += f"?page={page}"
            body = via_relay(url, timeout=35)
            if not body or len(body) < 30000: continue
            rows = parse_list(body, slug_is_resort)
            if not rows: break
            for r in rows:
                r["country"] = country
                r["slug"] = slug
                r["foreign_friction"] = ff
                r["foreign_note"] = FOREIGN_NOTES.get(country, "")
                r["fb_lat"] = lat0; r["fb_lng"] = lng0
            new = sum(1 for r in rows if r["id"] not in {x["id"] for x in all_rows})
            all_rows.extend(rows)
            print(f"  {country:>15} {slug:>28} p{page}: {len(rows)} (+{new})", file=sys.stderr)
            time.sleep(0.3)
            if len(rows) < 10: break

    seen = set(); dedup = []
    for r in all_rows:
        if r["id"] in seen: continue
        seen.add(r["id"]); dedup.append(r)
    print(f"\ntotal unique cards: {len(dedup)}", file=sys.stderr)

    for i, r in enumerate(dedup):
        cached = existing.get(r["id"])
        if cached and cached.get("lat") and cached["lat"] != r["fb_lat"]:
            r["lat"] = cached["lat"]; r["lng"] = cached["lng"]; r["acres"] = cached.get("acres")
            continue
        lat, lng, ac = fetch_detail(r["url"], timeout=25)
        r["lat"] = lat or r["fb_lat"]; r["lng"] = lng or r["fb_lng"]; r["acres"] = ac
        if i and i % 20 == 0:
            json.dump(dedup, open(out_path, "w"), ensure_ascii=False)
            print(f"  detail {i}/{len(dedup)}", file=sys.stderr)
        time.sleep(0.2)

    json.dump(dedup, open(out_path, "w"), ensure_ascii=False)
    from collections import Counter
    print(f"\ndone. {len(dedup)} saved", file=sys.stderr)
    print(dict(Counter(r["country"] for r in dedup).most_common()), file=sys.stderr)
