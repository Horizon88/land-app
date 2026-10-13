"""LandSearch — massive USA + Canada coverage expansion.

USA:
  Pacific coast     — CA (Marin, Mendocino, Big Sur/Monterey, Sonoma), OR, WA
  Southeast coast   — NC Outer Banks, SC Charleston/Hilton Head, GA Savannah,
                      FL Keys + Panhandle
  Northeast coast   — ME (Camden, Bar Harbor), NH, RI, CT
  Northwest ski     — Sun Valley, McCall, more MT/WY
  Great Lakes       — MI cottage country
  Hawaii            — Big Island, Kauai, Maui
  Alaska            — SE (Ketchikan), Kenai

Canada extras:
  Ontario cottage country (Muskoka, Bruce, Georgian Bay, Haliburton)
  Quebec Laurentides
  Rockies (Banff / Canmore / Golden — Alberta was previously stripped;
    re-add ski-adjacent parcels only)
"""
import json, re, subprocess, sys, time, urllib.parse, os

RELAY = "https://landrelay.flag-theory.workers.dev"

# (label, LandSearch slug, fallback lat, fallback lon, country)
COUNTIES = [
    # ---- USA Pacific coast ----
    ("Marin-CA",         "marin-county-ca",         38.05, -122.75, "USA"),
    ("Sonoma-CA",        "sonoma-county-ca",        38.60, -122.90, "USA"),
    ("Mendocino-CA",     "mendocino-county-ca",     39.35, -123.75, "USA"),
    ("Humboldt-CA",      "humboldt-county-ca",      40.75, -124.05, "USA"),
    ("Monterey-CA",      "monterey-county-ca",      36.30, -121.50, "USA"),
    ("San-LO-CA",        "san-luis-obispo-county-ca", 35.30, -120.65, "USA"),
    ("Santa-Barbara-CA", "santa-barbara-county-ca", 34.55, -119.90, "USA"),
    ("Santa-Cruz-CA",    "santa-cruz-county-ca",    37.10, -122.10, "USA"),
    # ---- USA OR + WA coast ----
    ("Lincoln-OR",       "lincoln-county-or",       44.70, -124.05, "USA"),
    ("Tillamook-OR",     "tillamook-county-or",     45.55, -123.85, "USA"),
    ("Clatsop-OR",       "clatsop-county-or",       46.05, -123.75, "USA"),
    ("Curry-OR",         "curry-county-or",         42.30, -124.30, "USA"),
    ("SanJuan-WA",       "san-juan-county-wa",      48.55, -122.95, "USA"),
    ("Whatcom-WA",       "whatcom-county-wa",       48.80, -122.15, "USA"),
    ("Jefferson-WA",     "jefferson-county-wa",     47.80, -123.85, "USA"),
    ("Clallam-WA",       "clallam-county-wa",       48.10, -123.85, "USA"),
    # ---- USA Northeast coast ----
    ("Knox-ME",          "knox-county-me",          44.10, -69.15, "USA"),
    ("Hancock-ME",       "hancock-county-me",       44.50, -68.35, "USA"),
    ("Lincoln-ME",       "lincoln-county-me",       44.00, -69.55, "USA"),
    ("Cumberland-ME",    "cumberland-county-me",    43.75, -70.30, "USA"),
    ("York-ME",          "york-county-me",          43.40, -70.75, "USA"),
    ("Rockingham-NH",    "rockingham-county-nh",    42.98, -71.05, "USA"),
    ("Washington-RI",    "washington-county-ri",    41.45, -71.65, "USA"),
    ("Newport-RI",       "newport-county-ri",       41.50, -71.30, "USA"),
    # ---- USA Southeast coast ----
    ("Dare-NC",          "dare-county-nc",          35.90, -75.65, "USA"),
    ("Currituck-NC",     "currituck-county-nc",     36.40, -75.90, "USA"),
    ("Brunswick-NC",     "brunswick-county-nc",     34.05, -78.20, "USA"),
    ("New-Hanover-NC",   "new-hanover-county-nc",   34.20, -77.90, "USA"),
    ("Beaufort-SC",      "beaufort-county-sc",      32.40, -80.75, "USA"),
    ("Charleston-SC",    "charleston-county-sc",    32.80, -79.95, "USA"),
    ("Georgetown-SC",    "georgetown-county-sc",    33.35, -79.30, "USA"),
    ("Chatham-GA",       "chatham-county-ga",       32.05, -81.10, "USA"),
    ("Glynn-GA",         "glynn-county-ga",         31.20, -81.50, "USA"),
    ("Camden-GA",        "camden-county-ga",        30.90, -81.65, "USA"),
    ("Monroe-FL",        "monroe-county-fl",        24.65, -81.40, "USA"),
    ("Walton-FL",        "walton-county-fl",        30.55, -86.15, "USA"),
    # ---- USA Great Lakes / cottage ----
    ("Leelanau-MI",      "leelanau-county-mi",      44.90, -86.00, "USA"),
    ("Charlevoix-MI",    "charlevoix-county-mi",    45.30, -85.20, "USA"),
    # ---- USA Hawaii + Alaska ----
    ("Hawaii-Big-Isl",   "hawaii-county-hi",        19.60, -155.55, "USA"),
    ("Kauai-HI",         "kauai-county-hi",         22.05, -159.50, "USA"),
    ("Maui-HI",          "maui-county-hi",          20.80, -156.30, "USA"),
    # ---- Canada cottage / wilderness ----
    ("Muskoka-ON",       "muskoka-district-municipality-on", 45.10, -79.30, "Canada"),
    ("Haliburton-ON",    "haliburton-county-on",    45.10, -78.55, "Canada"),
    ("Bruce-ON",         "bruce-county-on",         44.55, -81.30, "Canada"),
    ("Grey-ON",          "grey-county-on",          44.55, -80.75, "Canada"),
    ("Parry-Sound-ON",   "parry-sound-district-on", 45.35, -80.05, "Canada"),
    ("Kenora-ON",        "kenora-district-on",      50.00, -93.80, "Canada"),
    # ---- BC extras ----
    ("Squamish-Lillooet","squamish-lillooet-regional-district-bc", 50.10, -122.95, "British Columbia"),
    ("Central-Okanagan", "central-okanagan-regional-district-bc",  49.90, -119.50, "British Columbia"),
]

def via_relay(url, timeout=45):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

def parse_cards(html, fb_lat, fb_lon, region, country):
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
                c = ctx.get('center', [None, None])
                lon, lat = c[0], c[1]
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
            "region": region, "country": country, "id": m_id.group(1),
        })
    return rows

if __name__ == "__main__":
    out = "/tmp/expand_landsearch.json"
    all_rows = {}
    if os.path.exists(out):
        for r in json.load(open(out)):
            all_rows[r["url"]] = r
        print(f"loaded {len(all_rows)} existing", file=sys.stderr)

    for label, slug, lat, lon, country in COUNTIES:
        for path in ["", "/search/large-tracts"]:
            url = f"https://www.landsearch.com/properties/{slug}{path}"
            body = via_relay(url)
            if not body or len(body) < 30000: continue
            rows = parse_cards(body, lat, lon, label, country)
            new = 0
            for r in rows:
                if r["url"] not in all_rows: all_rows[r["url"]] = r; new += 1
            tag = "lg" if path else "df"
            print(f"  {label:>20} {tag}: +{new} (parsed {len(rows)})", file=sys.stderr)
            time.sleep(0.3)

    print(f"\nunique cards total: {len(all_rows)}", file=sys.stderr)
    json.dump(list(all_rows.values()), open(out, "w"))
