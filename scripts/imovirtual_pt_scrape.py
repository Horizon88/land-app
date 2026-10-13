"""Imovirtual (Portugal) — coastal + Serra da Estrela ski land scrape.

List page URL pattern: /pt/resultados/comprar/terreno/<distrito>[?page=N]
List page has __NEXT_DATA__ with searchAds.items (37 per page):
  id, title, slug, totalPrice.value, location.address.city.name
  (no coords, no area at list level)

Detail URL: /pt/anuncio/<slug>
Detail __NEXT_DATA__ has:
  coordinates.{latitude, longitude}
  description text — area shown as "N metros quadrados" or "N m²"
"""
import json, re, subprocess, sys, time, urllib.parse, os

RELAY = "https://landrelay.flag-theory.workers.dev"

# Portuguese districts to sweep — mix of coastal + Serra da Estrela ski
DISTRITOS = [
    # Ski / mountain
    ("Guarda",           "guarda",           40.55, -7.27),   # Serra da Estrela
    ("Castelo-Branco",   "castelo-branco",   40.00, -7.50),   # SE foothills
    ("Vila-Real",        "vila-real",        41.30, -7.75),
    ("Braganca",         "braganca",         41.80, -6.75),
    # Coastal / Algarve
    ("Faro",             "faro",             37.10, -7.90),
    ("Setubal",          "setubal",          38.55, -8.90),
    ("Lisboa",           "lisboa",           38.75, -9.15),
    ("Leiria",           "leiria",           39.75, -8.80),
    ("Aveiro",           "aveiro",           40.65, -8.65),
    ("Coimbra",          "coimbra",          40.20, -8.40),
    ("Porto",            "porto",            41.15, -8.60),
    ("Viana-do-Castelo", "viana-do-castelo", 41.70, -8.75),
    ("Braga",            "braga",            41.55, -8.42),
    # Interior — Alentejo big farms
    ("Beja",             "beja",             37.95, -7.85),
    ("Evora",            "evora",            38.55, -7.90),
    ("Portalegre",       "portalegre",       39.30, -7.45),
    # Islands
    ("Madeira",          "madeira",          32.75, -16.95),
    ("Azores",           "acores",           38.72, -27.22),
]

def via_relay(url, timeout=45):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

def parse_list_page(html, distrito_label, fb_lat, fb_lng):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m: return []
    try:
        d = json.loads(m.group(1))
        items = d["props"]["pageProps"]["data"]["searchAds"]["items"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return []
    rows = []
    for it in items:
        if it.get("estate") != "TERRAIN": continue
        price = it.get("totalPrice", {})
        if not price or not price.get("value"): continue
        try: usd = int(price["value"] * 1.08)  # EUR → USD
        except: continue
        loc = it.get("location", {}) or {}
        addr = loc.get("address") or {}
        city = (addr.get("city") or {}).get("name","") if addr.get("city") else ""
        prov = (addr.get("province") or {}).get("name","") if addr.get("province") else ""
        img_list = it.get("images") or []
        img = ""
        if img_list and img_list[0].get("large"):
            img = img_list[0]["large"]
        rows.append({
            "id": it["id"],
            "slug": it.get("slug",""),
            "url": f"https://www.imovirtual.com/pt/anuncio/{it['slug']}",
            "title": it.get("title","")[:140],
            "price_eur": price["value"],
            "price_usd": usd,
            "district": distrito_label,
            "city": city,
            "province": prov,
            "img": img,
            "fb_lat": fb_lat,
            "fb_lng": fb_lng,
        })
    return rows

def fetch_detail(url, timeout=30):
    """Return (lat, lng, sqm) for one detail page."""
    body = via_relay(url, timeout)
    if not body or len(body) < 50000:
        return None, None, None
    # Coords — pull from raw regex since __NEXT_DATA__ has them stringified
    lat = lng = None
    m = re.search(r'"latitude"\s*:\s*"?([-\d.]+).{0,60}?"longitude"\s*:\s*"?([-\d.]+)', body, re.S)
    if m:
        try:
            la, lo = float(m.group(1)), float(m.group(2))
            if 32 < la < 43 and -32 < lo < -6:
                lat, lng = la, lo
        except: pass
    # Area: extract from __NEXT_DATA__ JSON (parse properly to avoid
    # matching the meta-description at top of HTML which is a generic tagline).
    sqm = None
    m_nd = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', body, re.S)
    if m_nd:
        try:
            d = json.loads(m_nd.group(1))
            # Walk to find the ad object with a description field
            def find_ad(o, depth=0):
                if depth > 15: return None
                if isinstance(o, dict):
                    if "description" in o and isinstance(o["description"], str) and len(o["description"]) > 50 and ("m²" in o["description"] or "metros" in o["description"].lower() or "hectare" in o["description"].lower()):
                        return o["description"]
                    for v in o.values():
                        r = find_ad(v, depth+1)
                        if r: return r
                elif isinstance(o, list):
                    for vv in o:
                        r = find_ad(vv, depth+1)
                        if r: return r
                return None
            desc = find_ad(d)
            if desc:
                # Try "N m²" or "N metros quadrados"
                m_a = re.search(r'(\d[\d.,]*)\s*(?:m²|metros?\s*quadrados?|m2)\b', desc, re.I)
                if m_a:
                    n_str = m_a.group(1).replace(".","").replace(",",".")
                    try:
                        n = float(n_str)
                        if 50 < n < 10_000_000: sqm = n
                    except: pass
                if not sqm:
                    m_ha = re.search(r'(\d[\d.,]*)\s*hectares?\b', desc, re.I)
                    if m_ha:
                        try: sqm = float(m_ha.group(1).replace(".","").replace(",",".")) * 10000
                        except: pass
        except json.JSONDecodeError:
            pass
    return lat, lng, sqm

if __name__ == "__main__":
    out_path = "/tmp/imovirtual_pt.json"
    existing = {}
    if os.path.exists(out_path):
        for r in json.load(open(out_path)):
            existing[str(r["id"])] = r
        print(f"loaded {len(existing)} existing", file=sys.stderr)

    all_rows = []
    for label, slug, lat0, lng0 in DISTRITOS:
        for page in range(1, 6):
            url = f"https://www.imovirtual.com/pt/resultados/comprar/terreno/{slug}"
            if page > 1: url += f"?page={page}"
            body = via_relay(url, timeout=35)
            if not body or len(body) < 30000: continue
            rows = parse_list_page(body, label, lat0, lng0)
            if not rows:
                # End of pages
                break
            all_rows.extend(rows)
            print(f"  {label:<20} p{page}: parsed {len(rows)}", file=sys.stderr)
            time.sleep(0.3)
            if len(rows) < 20: break  # partial page = last page

    # Dedup by id
    seen = set(); deduped = []
    for r in all_rows:
        rid = str(r["id"])
        if rid in seen: continue
        seen.add(rid)
        deduped.append(r)
    print(f"\ntotal unique: {len(deduped)}", file=sys.stderr)

    # Phase 2: detail-fetch coords + area
    for i, r in enumerate(deduped):
        rid = str(r["id"])
        cached = existing.get(rid)
        if cached and cached.get("lat") and cached.get("sqm"):
            r["lat"] = cached["lat"]; r["lng"] = cached["lng"]; r["sqm"] = cached["sqm"]
            continue
        lat, lng, sqm = fetch_detail(r["url"], timeout=25)
        r["lat"] = lat or r["fb_lat"]
        r["lng"] = lng or r["fb_lng"]
        r["sqm"] = sqm
        if i and i % 25 == 0:
            json.dump(deduped, open(out_path, "w"), ensure_ascii=False)
            print(f"  detail {i}/{len(deduped)}", file=sys.stderr)
        time.sleep(0.2)

    json.dump(deduped, open(out_path, "w"), ensure_ascii=False)
    n_coord = sum(1 for r in deduped if r.get("lat") and abs(r["lat"] - r["fb_lat"]) > 0.01)
    n_area = sum(1 for r in deduped if r.get("sqm"))
    print(f"\ndone. {len(deduped)} saved (real coords: {n_coord}, with area: {n_area})", file=sys.stderr)
