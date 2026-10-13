"""Argenprop — Argentine mountain land (terrenos) + Patagonia estancias (campos).

Server-rendered, no bot wall. Cards carry structured attributes:
  data-item-card (id), montonormalizado (price), idmoneda (2 = USD),
  "<n> m² Total" fragment, address + locality text, img data-src.

No coords on list or detail pages (map loads dynamically) — rows are pinned
at the search-location centroid, geocode_src marks the precision.

Emits /tmp/argenprop.json for argenprop_merge.py.
"""
import json, re, subprocess, sys, time, os

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# (display, slug, centroid lat, lng, category, max pages)
SEARCHES = [
    ("Bariloche",              "bariloche",               -41.13, -71.31, "terrenos", 12),
    ("San Martín de los Andes","san-martin-de-los-andes", -40.16, -71.35, "terrenos", 8),
    ("Villa La Angostura",     "villa-la-angostura",      -40.76, -71.64, "terrenos", 8),
    ("El Bolsón",              "el-bolson",               -41.96, -71.53, "terrenos", 6),
    ("Esquel",                 "esquel",                  -42.91, -71.32, "terrenos", 5),
    ("Trevelin",               "trevelin",                -43.08, -71.46, "terrenos", 4),
    ("Ushuaia",                "ushuaia",                 -54.80, -68.30, "terrenos", 5),
    ("Junín de los Andes",     "junin-de-los-andes",      -39.95, -71.07, "terrenos", 4),
    ("Villa Pehuenia",         "villa-pehuenia",          -38.88, -71.17, "terrenos", 4),
    ("Malargüe",               "malargue",                -35.47, -69.58, "terrenos", 4),
    ("Luján de Cuyo",          "lujan-de-cuyo",           -33.05, -68.88, "terrenos", 6),
    ("Tunuyán",                "tunuyan",                 -33.58, -69.02, "terrenos", 5),
    ("Potrerillos",            "potrerillos",             -32.95, -69.20, "terrenos", 4),
    # estancia-scale land by province
    ("Río Negro (campo)",      "rio-negro",               -40.80, -70.00, "campos", 8),
    ("Neuquén (campo)",        "neuquen",                 -38.60, -70.50, "campos", 8),
    ("Chubut (campo)",         "chubut",                  -43.80, -69.50, "campos", 8),
    ("Santa Cruz (campo)",     "santa-cruz",              -48.80, -70.00, "campos", 5),
    ("Tierra del Fuego (campo)","tierra-del-fuego",       -54.30, -67.80, "campos", 3),
    ("Mendoza (campo)",        "mendoza",                 -34.60, -68.50, "campos", 6),
]

CARD_HREF = re.compile(r'href="(/(?:terreno|campo)[^"]*--(\d+))"')

def curl(url, timeout=25):
    try:
        return subprocess.run(["curl", "-sL", "-m", str(timeout), "-A", UA,
                               "-H", "Accept-Language: es-AR,es;q=0.9,en;q=0.5", url],
                              capture_output=True, text=True, timeout=timeout + 5).stdout
    except Exception:
        return ""

def es_num(s):
    """'1.500,5' → 1500.5 ; '719,0' → 719.0 ; '719' → 719.0"""
    s = s.strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None

def parse_cards(h):
    pos = [(m.start(), m.group(1), m.group(2)) for m in CARD_HREF.finditer(h)]
    seen, cards = set(), []
    for p, u, cid in pos:
        if cid not in seen:
            seen.add(cid)
            cards.append((p, u, cid))
    out = []
    for i, (p, u, cid) in enumerate(cards):
        end = cards[i + 1][0] if i + 1 < len(cards) else p + 8000
        c = h[p:end]
        m_price = re.search(r'idmoneda="(\d)"[^>]*montonormalizado="(\d+)"', c)
        if not m_price:
            m_price = re.search(r'montonormalizado="(\d+)"', c)
            moneda, monto = None, m_price.group(1) if m_price else None
        else:
            moneda, monto = m_price.group(1), m_price.group(2)
        usd_text = bool(re.search(r'(?:USD|U\$S)\s*[\d.]', c))
        m_m2 = re.search(r'([\d.,]+)\s*m(?:&#xB2;|²|2)\s*Total', c)
        m_alt = re.search(r'alt="([^"]{5,120})"', c)
        m_img = re.search(r'data-src="(https://[^"]+\.(?:jpg|jpeg|webp)[^"]*)"', c)
        loc = re.search(r'(?:Terreno|Campo|Lote) en Venta en ([^<]{3,80})<', c)
        out.append({
            "id": cid, "path": u,
            "moneda": moneda, "monto": int(monto) if monto else None,
            "usd_text": usd_text,
            "m2": es_num(m_m2.group(1)) if m_m2 else None,
            "title": (m_alt.group(1) if m_alt else "").strip(),
            "loc_text": (loc.group(1) if loc else "").strip(),
            "img": m_img.group(1) if m_img else "",
        })
    return out

def detail_surface_m2(path):
    """Campos cards carry no size — pull hectares (or m²) off the detail page."""
    h = curl(f"https://www.argenprop.com{path}")
    if not h:
        return None
    m = re.search(r'([\d.,]+)\s*(?:ha\b|hect\w*)', h, re.I)
    if m:
        ha = es_num(m.group(1))
        if ha and 0.1 <= ha <= 500_000:
            return ha * 10000
    m = re.search(r'([\d.,]+)\s*m(?:&#xB2;|²|2)\s*Total', h)
    if m:
        return es_num(m.group(1))
    return None

if __name__ == "__main__":
    out, seen = [], set()
    for display, slug, lat, lng, cat, maxpg in SEARCHES:
        n0 = len(out)
        for pg in range(1, maxpg + 1):
            url = f"https://www.argenprop.com/{cat}/venta/{slug}" + (f"?pagina-{pg}" if pg > 1 else "")
            h = curl(url)
            if not h or len(h) < 30000:
                break
            cards = parse_cards(h)
            new = 0
            for c in cards:
                if c["id"] in seen:
                    continue
                seen.add(c["id"])
                c["region"] = display
                c["lat"], c["lng"] = lat, lng
                c["cat"] = cat
                out.append(c)
                new += 1
            if new == 0:
                break
            time.sleep(0.4)
        print(f"  {display:<26} +{len(out)-n0}", file=sys.stderr)
        json.dump(out, open("/tmp/argenprop.json", "w"))

    # campos need a detail fetch for surface
    need = [c for c in out if c["cat"] == "campos" and not c.get("m2")]
    print(f"fetching surface for {len(need)} campos…", file=sys.stderr)
    for i, c in enumerate(need):
        c["m2"] = detail_surface_m2(c["path"])
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{len(need)}", file=sys.stderr)
            json.dump(out, open("/tmp/argenprop.json", "w"))
        time.sleep(0.35)
    json.dump(out, open("/tmp/argenprop.json", "w"))
    sized = sum(1 for c in out if c.get("m2"))
    print(f"TOTAL {len(out)} ({sized} with size) -> /tmp/argenprop.json", file=sys.stderr)
