"""LandSearch — South Coast Massachusetts + Cape Cod + Islands.

Counties:
- Barnstable: Cape Cod (Provincetown → Sandwich)
- Bristol: South Coast (New Bedford, Fall River, Westport, Dartmouth)
- Plymouth: South Shore + Plymouth/Wareham
- Dukes: Martha's Vineyard
- Nantucket: Nantucket
- Norfolk: south part touches Boston metro coast
"""
import json, re, subprocess, sys, time, urllib.parse, os

RELAY = "https://landrelay.flag-theory.workers.dev"

COUNTIES = [
    ("Cape-Cod-MA",    "barnstable-county-ma", 41.70, -70.30),
    ("Bristol-MA",     "bristol-county-ma",    41.70, -70.95),
    ("Plymouth-MA",    "plymouth-county-ma",   41.96, -70.71),
    ("Marthas-VY-MA",  "dukes-county-ma",      41.40, -70.65),
    ("Nantucket-MA",   "nantucket-county-ma",  41.27, -70.10),
    ("Norfolk-MA",     "norfolk-county-ma",    42.18, -71.20),
]

def via_relay(url, timeout=45):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

def parse_cards(html, fb_lat, fb_lon, region):
    rows = []
    for art in re.split(r'<article class="preview', html)[1:]:
        m_id = re.search(r'data-id="(\d+)"', art)
        m_ctx = re.search(r'data-context="([^"]+)"', art)
        m_href = re.search(r'href="(/properties/[^"]+)"', art)
        m_price = re.search(r'\$([\d,]+)', art)
        m_size = re.search(r'(\d+(?:\.\d+)?)\s*(?:acres?|ac\b)', art, re.I)
        m_loc = re.search(r'class="preview__location[^"]*"[^>]*>([^<]+)<', art)
        m_alt = re.search(r'alt="([^"]+)"', art)
        if not (m_id and m_href and m_price): continue
        lat, lon = None, None
        if m_ctx:
            try:
                ctx = json.loads(m_ctx.group(1).replace('&quot;','"'))
                center = ctx.get('center', [None, None])
                lon, lat = center[0], center[1]
            except: pass
        if not lat: lat, lon = fb_lat, fb_lon
        acres = None
        if m_size:
            try: acres = float(m_size.group(1))
            except: pass
        if not acres or acres < 0.1: continue
        price = int(m_price.group(1).replace(",",""))
        if price < 5000: continue
        rows.append({
            "url": "https://www.landsearch.com" + m_href.group(1),
            "title": (m_alt.group(1) if m_alt else "")[:140],
            "price_usd": price, "acres": acres,
            "lat": lat, "lon": lon,
            "loc": (m_loc.group(1).strip() if m_loc else "")[:60],
            "region": region, "id": m_id.group(1),
        })
    return rows

if __name__ == "__main__":
    out = "/tmp/usa_landsearch.json"
    all_rows = {}
    if os.path.exists(out):
        for r in json.load(open(out)):
            all_rows[r["url"]] = r
        print(f"loaded {len(all_rows)} existing USA rows", file=sys.stderr)

    for label, slug, lat, lon in COUNTIES:
        for path in ["", "/search/large-tracts"]:
            url = f"https://www.landsearch.com/properties/{slug}{path}"
            body = via_relay(url)
            if not body or len(body) < 30000: continue
            rows = parse_cards(body, lat, lon, label)
            new = 0
            for r in rows:
                if r["url"] not in all_rows:
                    all_rows[r["url"]] = r; new += 1
            tag = "lg" if path else "df"
            print(f"  {label:>18} {tag}: +{new} (parsed {len(rows)})", file=sys.stderr)
            time.sleep(0.4)

    print(f"\nunique USA cards total: {len(all_rows)}", file=sys.stderr)
    json.dump(list(all_rows.values()), open(out, "w"))
