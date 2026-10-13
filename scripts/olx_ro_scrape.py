"""OLX Romania land scrape — Carpathian ski counties.

Card list: /imobiliare/terenuri/<judet>/ → id, title, price (EUR), area (m²)
Detail:   /d/oferta/...-ID<X>.html → lat/lng via "latitude":..., "longitude":...

Romanian counties covered (top Carpathian ski areas):
- Brasov:    Poiana Brasov, Predeal, Bran, Rasnov
- Prahova:   Sinaia, Busteni, Azuga (Valea Prahovei)
- Suceava:   Vatra Dornei, Câmpulung
- Hunedoara: Straja, Parâng
- Harghita:  Harghita Mădăraș, Mt Madarasi
- Maramures: Borșa, Cavnic, Suior
- Alba:      Arieșeni, Vârtop
- Sibiu:     Păltiniș, Bâlea
"""
import json, re, subprocess, sys, time, urllib.parse, os

RELAY = "https://landrelay.flag-theory.workers.dev"

JUDETE = [
    ("Brasov",    "brasov",    45.65, 25.60),
    ("Prahova",   "prahova",   45.10, 25.74),
    ("Suceava",   "suceava",   47.65, 26.25),
    ("Hunedoara", "hunedoara", 45.75, 22.90),
    ("Harghita",  "harghita",  46.36, 25.80),
    ("Maramures", "maramures", 47.66, 24.00),
    ("Alba",      "alba",      46.07, 23.57),
    ("Sibiu",     "sibiu",     45.79, 24.15),
    ("Bihor",     "bihor",     47.07, 22.40),
    ("Cluj",      "cluj",      46.78, 23.60),
]

def via_relay(url, timeout=45):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

def parse_cards(html, judet_label):
    rows = []
    cards = re.split(r'<div[^>]*data-cy="l-card"', html)[1:]
    for c in cards:
        m_id = re.search(r'id="(\d+)"', c[:200])
        m_href = re.search(r'href="(/d/oferta/[^"]+\.html[^"]*)"', c)
        m_title = re.search(r'<h6[^>]*>([^<]+)</h6>', c) or re.search(r'<h4[^>]*>([^<]+)</h4>', c)
        m_price = re.search(r'>([\d\s.,]+)\s*(€|EUR|lei)', c)
        m_area = re.search(r'(\d[\d\s,.]*)\s*(mp|m²|ha)', c, re.I)
        m_loc = re.search(r'data-testid="location-date"[^>]*>([^<]+)', c)
        if not (m_id and m_price): continue
        # area
        sqm = None
        if m_area:
            n_str = m_area.group(1).replace(" ","").replace(",","").replace(".","")
            try:
                n = int(n_str)
                if m_area.group(2).lower() == "ha":
                    sqm = n * 10000
                else:
                    sqm = n
            except: pass
        # price
        p_str = m_price.group(1).replace(" ","").replace(",","").replace(".","")
        try:
            price = int(p_str)
        except: continue
        cur = "EUR" if m_price.group(2) in ("€","EUR") else "RON"
        # Title can also encode area sometimes
        title = (m_title.group(1).strip() if m_title else "")[:140]
        loc = m_loc.group(1).strip() if m_loc else judet_label
        href = m_href.group(1) if m_href else None
        rows.append({
            "id": m_id.group(1), "judet": judet_label,
            "title": title, "price": price, "cur": cur,
            "sqm": sqm, "loc": loc[:60],
            "url": "https://www.olx.ro" + href if href else None,
        })
    return rows

_LAT_PATS = [
    re.compile(r'"latitude"\s*:\s*"?([-\d.]+)[^"\d.]'),
    re.compile(r'\\"lat\\"\s*:\s*([-\d.]+)'),
    re.compile(r'\blat\\?\"?\s*:\s*\\?\"?([-\d.]+)'),
]
_LNG_PATS = [
    re.compile(r'"longitude"\s*:\s*"?([-\d.]+)[^"\d.]'),
    re.compile(r'\\"lng\\"\s*:\s*([-\d.]+)'),
    re.compile(r'\blng\\?\"?\s*:\s*\\?\"?([-\d.]+)'),
    re.compile(r'\blon\\?\"?\s*:\s*\\?\"?([-\d.]+)'),
]
def fetch_detail_coords(url, timeout=30):
    """Extract lat/lng from OLX RO detail (escaped JSON in Next.js stream)."""
    body = via_relay(url, timeout)
    if not body or len(body) < 50000:
        return None, None
    lat = lng = None
    for p in _LAT_PATS:
        m = p.search(body)
        if m:
            try: lat = float(m.group(1)); break
            except: pass
    for p in _LNG_PATS:
        m = p.search(body)
        if m:
            try: lng = float(m.group(1)); break
            except: pass
    # RO is roughly 43-48 N, 20-30 E
    if lat and lng and 42 < lat < 49 and 19 < lng < 31:
        return lat, lng
    return None, None

if __name__ == "__main__":
    out_path = "/tmp/olx_ro.json"
    existing = {}
    if os.path.exists(out_path):
        for r in json.load(open(out_path)):
            existing[r["id"]] = r
        print(f"loaded {len(existing)} existing", file=sys.stderr)

    # Phase 1: collect all cards
    all_cards = []
    for label, slug, lat0, lng0 in JUDETE:
        for page in range(1, 9):
            url = f"https://www.olx.ro/imobiliare/terenuri/{slug}/?page={page}" if page > 1 else f"https://www.olx.ro/imobiliare/terenuri/{slug}/"
            body = via_relay(url, timeout=35)
            if not body or len(body) < 30000: continue
            rows = parse_cards(body, label)
            new = sum(1 for r in rows if r["id"] not in {x["id"] for x in all_cards})
            for r in rows:
                r["judet_label"] = label
                r["fb_lat"] = lat0; r["fb_lng"] = lng0
            all_cards.extend(rows)
            print(f"  {label} p{page}: parsed {len(rows)} (+{new} unique)", file=sys.stderr)
            time.sleep(0.3)

    # Dedup
    seen = set()
    deduped = []
    for r in all_cards:
        if r["id"] in seen: continue
        seen.add(r["id"])
        deduped.append(r)
    print(f"\ntotal unique cards: {len(deduped)}", file=sys.stderr)

    # Phase 2: fetch coords. Only reuse cached coord if it's REAL (not the
    # judet-centroid fallback — otherwise we'd never actually fetch).
    for i, r in enumerate(deduped):
        cached = existing.get(r["id"])
        if cached and cached.get("lat") and abs(cached["lat"] - r["fb_lat"]) > 0.005:
            r["lat"] = cached["lat"]
            r["lng"] = cached["lng"]
            continue
        if not r["url"]:
            r["lat"] = r["fb_lat"]; r["lng"] = r["fb_lng"]
            continue
        lat, lng = fetch_detail_coords(r["url"], timeout=30)
        r["lat"] = lat or r["fb_lat"]
        r["lng"] = lng or r["fb_lng"]
        if i and i % 25 == 0:
            json.dump(deduped, open(out_path, "w"), ensure_ascii=False)
            print(f"  coords {i}/{len(deduped)}", file=sys.stderr)
        time.sleep(0.2)

    json.dump(deduped, open(out_path, "w"), ensure_ascii=False)
    print(f"\ndone. {len(deduped)} cards saved", file=sys.stderr)
    n_with_area = sum(1 for r in deduped if r.get("sqm"))
    n_real_coord = sum(1 for r in deduped if r.get("lat") and abs(r["lat"] - r["fb_lat"]) > 0.001)
    print(f"  with area: {n_with_area}  with real coords: {n_real_coord}", file=sys.stderr)
