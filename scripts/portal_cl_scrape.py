"""Portalinmobiliario (MercadoLibre Chile) — Andes ski + coastal land scrape.

Regions with premier Chilean ski:
- Región Metropolitana: Farellones, Valle Nevado, El Colorado (all above Santiago)
- Valparaíso:           Portillo (Los Andes)
- Ñuble:                Nevados de Chillán
- Araucanía:            Corralco, Llaima
- Los Lagos:            Antillanca, Osorno (volcanic ski)
- Aysén:                Cerro Castor / Patagonia heli

Cards: 48 per page. Currency: UF (Unidad de Fomento, ~$40 USD in mid-2026)
or CLP (Chilean peso, ~$0.001 USD). Detail pages have gps coords in JSON.
"""
import json, re, subprocess, sys, time, urllib.parse, os

RELAY = "https://landrelay.flag-theory.workers.dev"

REGIONS = [
    ("Santiago-Andes",  "sitio/metropolitana",          -33.35, -70.30),  # Farellones/El Colorado/Valle Nevado
    ("Valparaiso",      "sitio/valparaiso",             -32.80, -70.20),  # Portillo
    ("Nuble",           "sitio/nuble",                  -36.90, -71.50),  # Nevados de Chillán
    ("Araucania",       "sitio/araucania",              -38.75, -71.60),  # Corralco/Llaima
    ("Los-Lagos",       "sitio/los-lagos",              -41.10, -72.55),  # Antillanca/Osorno
    ("Los-Rios",        "sitio/los-rios",               -39.80, -72.20),  # Lakes
    ("Aysen",           "sitio/aysen",                  -46.00, -73.00),  # Patagonia
    ("Magallanes",      "sitio/magallanes",             -53.15, -70.90),  # Torres del Paine region
    # Coastal
    ("Valparaiso-coast","sitio/valparaiso/con-frente-al-mar", -33.00, -71.60),
]

def via_relay(url, timeout=45):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

def parse_cards(html, region_label, fb_lat, fb_lng):
    rows = []
    seen = set()
    for m in re.finditer(r'href="(https?://portalinmobiliario\.com/(MLC-\d+)[^"]*)"', html):
        url, mlc = m.group(1).split("#")[0], m.group(2)
        if mlc in seen: continue
        seen.add(mlc)
        start = max(0, m.start()-500); end = min(len(html), m.end()+2500)
        ctx = html[start:end]
        m_price = re.search(r'andes-money-amount__fraction[^>]*>([\d.,]+)<', ctx)
        m_cur = re.search(r'andes-money-amount__currency-symbol[^>]*>([^<]+)<', ctx)
        m_size = re.search(r'([\d.,]+)\s*(m²|m2|hectáreas?|ha)\b', ctx, re.I)
        m_title = re.search(r'poly-component__title[^>]*>([^<]{5,200})<', ctx)
        m_loc = re.search(r'poly-component__location[^>]*>([^<]{3,120})<', ctx)
        if not (m_price and m_cur): continue
        # Chilean numbers use `.` as thousands separator, `,` as decimal
        cur = m_cur.group(1).strip()
        price_str = m_price.group(1).replace(".","").replace(",",".")
        try:
            price = float(price_str)
        except: continue
        sqm = None
        if m_size:
            n_str = m_size.group(1).replace(".","").replace(",",".")
            unit = m_size.group(2).lower()
            try:
                n = float(n_str)
                sqm = n * 10000 if "ha" in unit else n
            except: pass
        rows.append({
            "mlc": mlc, "url": url,
            "region": region_label,
            "price": price, "cur": cur,
            "sqm": sqm,
            "title": (m_title.group(1).strip() if m_title else "")[:140],
            "loc": (m_loc.group(1).strip() if m_loc else "")[:80],
            "fb_lat": fb_lat, "fb_lng": fb_lng,
        })
    return rows

def fetch_detail_coords(url, timeout=30):
    body = via_relay(url, timeout)
    if not body or len(body) < 30000:
        return None, None
    # MercadoLibre uses "latitude":"XX.XX" JSON string quoted format
    m = re.search(r'"latitude"\s*:\s*"?([-\d.]+)[^"\d.].{0,120}?"longitude"\s*:\s*"?([-\d.]+)', body, re.S)
    if m:
        try:
            lat, lng = float(m.group(1)), float(m.group(2))
            # Chile is roughly -56 to -17 lat, -75 to -66 lng
            if -57 < lat < -17 and -76 < lng < -66:
                return lat, lng
        except: pass
    return None, None

if __name__ == "__main__":
    out_path = "/tmp/portal_cl.json"
    existing = {}
    if os.path.exists(out_path):
        for r in json.load(open(out_path)):
            existing[r["mlc"]] = r
        print(f"loaded {len(existing)} existing", file=sys.stderr)

    all_cards = []
    for label, path, lat0, lng0 in REGIONS:
        for page in range(1, 11):
            offset = (page - 1) * 48 + 1
            if page > 1:
                url = f"https://www.portalinmobiliario.com/venta/{path}/_Desde_{offset}_NoIndex_True"
            else:
                url = f"https://www.portalinmobiliario.com/venta/{path}/"
            body = via_relay(url, timeout=35)
            if not body or len(body) < 30000: continue
            rows = parse_cards(body, label, lat0, lng0)
            new = sum(1 for r in rows if r["mlc"] not in {x["mlc"] for x in all_cards})
            all_cards.extend(rows)
            print(f"  {label:>18} p{page}: parsed {len(rows)} (+{new})", file=sys.stderr)
            time.sleep(0.3)
            if len(rows) < 5: break  # end of results

    # Dedup
    seen = set(); deduped = []
    for r in all_cards:
        if r["mlc"] in seen: continue
        seen.add(r["mlc"])
        deduped.append(r)
    print(f"\ntotal unique cards: {len(deduped)}", file=sys.stderr)

    # Phase 2: coords
    for i, r in enumerate(deduped):
        cached = existing.get(r["mlc"])
        if cached and cached.get("lat") and abs(cached["lat"] - r["fb_lat"]) > 0.005:
            r["lat"] = cached["lat"]; r["lng"] = cached["lng"]
            continue
        lat, lng = fetch_detail_coords(r["url"], timeout=25)
        r["lat"] = lat or r["fb_lat"]
        r["lng"] = lng or r["fb_lng"]
        if i and i % 25 == 0:
            json.dump(deduped, open(out_path, "w"), ensure_ascii=False)
            print(f"  coords {i}/{len(deduped)}", file=sys.stderr)
        time.sleep(0.2)

    json.dump(deduped, open(out_path, "w"), ensure_ascii=False)
    n_real = sum(1 for r in deduped if r.get("lat") and abs(r["lat"] - r["fb_lat"]) > 0.01)
    print(f"\ndone. {len(deduped)} saved (real coords: {n_real})", file=sys.stderr)
