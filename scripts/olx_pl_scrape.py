"""OLX Poland (.pl) land scrape — Tatra / Beskids / Sudetes ski regions.

Same OLX engine + parser as olx_ro_scrape.py — currency is PLN (zł).

Provinces (województwa):
- małopolskie   — Zakopane, Tatra Mts, Kasprowy Wierch
- śląskie       — Beskids (Szczyrk, Wisła, Korbielów)
- podkarpackie  — Bieszczady (Ustrzyki, Puławy)
- dolnośląskie  — Karkonosze (Karpacz, Szklarska Poręba)
"""
import json, re, subprocess, sys, time, urllib.parse, os

RELAY = "https://landrelay.flag-theory.workers.dev"

WOJ = [
    ("Malopolska",   "malopolskie",   49.30, 20.00),   # Zakopane area
    ("Slaskie",      "slaskie",       49.70, 19.00),   # Beskids
    ("Podkarpackie", "podkarpackie",  49.30, 22.30),   # Bieszczady
    ("Dolnoslaskie", "dolnoslaskie",  50.80, 15.70),   # Karkonosze / Sudetes
]

def via_relay(url, timeout=45):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

def parse_cards(html, woj_label):
    rows = []
    cards = re.split(r'<div[^>]*data-cy="l-card"', html)[1:]
    for c in cards:
        m_id = re.search(r'id="(\d+)"', c[:200])
        m_href = re.search(r'href="(/d/oferta/[^"]+\.html[^"]*)"', c)
        m_title = re.search(r'<h4[^>]*>([^<]+)</h4>', c) or re.search(r'<h6[^>]*>([^<]+)</h6>', c)
        m_price = re.search(r'>([\d\s.,]+)\s*(zł|PLN|€|EUR)', c)
        # Area: prefer the explicit "—X m²" label that OLX renders inside the card metadata.
        # Pattern: `</svg>902 m² ·` or `>5,000 m² <`. Only search the first 4KB to avoid
        # bleeding into the next card (l-card splits aren't clean).
        c_head = c[:4000]
        m_area = re.search(r'</svg>\s*(\d{1,3}(?:[ .,]\d+)?(?:[ .,]\d{3})*)\s*(m²|m2|mp|ha)\b', c_head, re.I)
        if not m_area:
            m_area = re.search(r'>\s*(\d{1,3}(?:[.,]\d+)?(?:[ .]?\d{3})*)\s*(m²|m2|ha)\s*[<·-]', c_head, re.I)
        m_loc = re.search(r'data-testid="location-date"[^>]*>([^<]+)', c)
        if not (m_id and m_price): continue
        sqm = None
        if m_area:
            unit = m_area.group(2).lower()
            n_str = m_area.group(1).replace(" ", "")
            try:
                if unit == "ha":
                    # PL: comma OR period can be decimal separator. Treat both as decimal.
                    val = float(n_str.replace(",", "."))
                    sqm = val * 10000
                else:
                    # m² area is integer; thousands separators are spaces (already stripped),
                    # commas, or periods. Strip them all.
                    val = int(n_str.replace(",", "").replace(".", ""))
                    sqm = val
            except: pass
        p_str = m_price.group(1).replace(" ","").replace(",","").replace(".","")
        try:
            price = int(p_str)
        except: continue
        cur = "PLN" if m_price.group(2) in ("zł","PLN") else "EUR"
        title = (m_title.group(1).strip() if m_title else "")[:140]
        loc = (m_loc.group(1).strip() if m_loc else woj_label)[:60]
        href = m_href.group(1) if m_href else None
        # decode HTML entities like &quot;
        title = title.replace("&quot;",'"').replace("&amp;","&").replace("&nbsp;"," ")
        rows.append({
            "id": m_id.group(1), "woj": woj_label,
            "title": title, "price": price, "cur": cur,
            "sqm": sqm, "loc": loc,
            "url": "https://www.olx.pl" + href if href else None,
        })
    return rows

_LAT_PATS = [
    re.compile(r'"latitude"\s*:\s*"?([-\d.]+)[^"\d.]'),
    re.compile(r'\blat\\?\"?\s*:\s*\\?\"?([-\d.]+)'),
]
_LNG_PATS = [
    re.compile(r'"longitude"\s*:\s*"?([-\d.]+)[^"\d.]'),
    re.compile(r'\blng\\?\"?\s*:\s*\\?\"?([-\d.]+)'),
    re.compile(r'\blon\\?\"?\s*:\s*\\?\"?([-\d.]+)'),
]
def fetch_detail_coords(url, timeout=30):
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
    if lat and lng and 48 < lat < 56 and 13 < lng < 25:
        return lat, lng
    return None, None

if __name__ == "__main__":
    out_path = "/tmp/olx_pl.json"
    existing = {}
    if os.path.exists(out_path):
        for r in json.load(open(out_path)):
            existing[r["id"]] = r
        print(f"loaded {len(existing)} existing", file=sys.stderr)

    all_cards = []
    for label, slug, lat0, lng0 in WOJ:
        for page in range(1, 9):
            sep = "&" if "?" in slug else "?"
            url = f"https://www.olx.pl/nieruchomosci/dzialki/{slug}/{sep}page={page}" if page > 1 else f"https://www.olx.pl/nieruchomosci/dzialki/{slug}/"
            body = via_relay(url, timeout=35)
            if not body or len(body) < 30000: continue
            rows = parse_cards(body, label)
            for r in rows:
                r["woj_label"] = label
                r["fb_lat"] = lat0; r["fb_lng"] = lng0
            new = sum(1 for r in rows if r["id"] not in {x["id"] for x in all_cards})
            all_cards.extend(rows)
            print(f"  {label} p{page}: parsed {len(rows)} (+{new})", file=sys.stderr)
            time.sleep(0.3)

    seen = set()
    deduped = []
    for r in all_cards:
        if r["id"] in seen: continue
        seen.add(r["id"])
        deduped.append(r)
    print(f"\ntotal unique cards: {len(deduped)}", file=sys.stderr)

    for i, r in enumerate(deduped):
        if r["id"] in existing and existing[r["id"]].get("lat"):
            r["lat"] = existing[r["id"]]["lat"]
            r["lng"] = existing[r["id"]]["lng"]
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
    n_real_coord = sum(1 for r in deduped if r.get("lat") and abs(r["lat"] - r["fb_lat"]) > 0.001)
    print(f"\ndone. {len(deduped)} saved (real coords: {n_real_coord})", file=sys.stderr)
