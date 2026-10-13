"""BAM detail-page scrape via CF relay — v2.

Each /th/th/npa/property/<id> page has the full structured asset record
embedded as escaped JSON inside the Next.js streamed payload:

  "id\":<id>,\"market_code\":\"...\",\"npa_type\":\"...\",
  \"province_name\":\"...\",\"city_name\":\"...\",
  \"gps_lat1\":\"<lat>\",\"gps_long1\":\"<lng>\",
  \"rai\":\"X\",\"ngan\":\"Y\",\"wa\":\"Z\",\"center_price\":\"<thb>\"

So we anchor on `\"id\\":<bam_id>,\\"market_code` and pull each field
from the surrounding chunk. Falls back to JSON-LD for name + image.
"""
import json, re, subprocess, sys, time, urllib.parse

RELAY = "https://landrelay.flag-theory.workers.dev"

def via_relay(url, timeout=45):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

def _esc(field, val_pat):
    """Build regex for `\"field\":\"<val>\"` in escaped JSON stream."""
    return re.compile(r'\\"' + re.escape(field) + r'\\":\\"(' + val_pat + r')\\"')

def _esc_num(field):
    """Build regex for `\"field\":<number>` (unquoted)."""
    return re.compile(r'\\"' + re.escape(field) + r'\\":([-\d.]+)')

def parse_detail(h, bam_id):
    # Locate the canonical asset record
    anchor = re.search(r'\\"id\\":' + re.escape(str(bam_id)) + r',\\"market_code\\"', h)
    if not anchor:
        return None
    # Take a big chunk after the anchor — the record is ~3-5 KB
    chunk = h[anchor.start():anchor.start() + 8000]

    def f(field, val_pat=r'[^"\\\\]*'):
        m = _esc(field, val_pat).search(chunk)
        return m.group(1) if m else ""

    def fn(field):
        m = _esc_num(field).search(chunk)
        return m.group(1) if m else ""

    province = f("province_name")
    district = f("city_name")
    npa_type = f("npa_type")
    col_type = f("col_typedesc")
    asset_type = npa_type or col_type
    rai = f("rai") or "0"
    ngan = f("ngan") or "0"
    wa = f("wa") or "0"
    usable = f("usabled_area") or "0"
    area_m = f("area_meter") or "0"
    lat = f("gps_lat1") or ""
    lng = f("gps_long1") or ""
    price = f("center_price") or fn("center_price") or "0"
    state = f("asset_state")  # "ทรัพย์พร้อมขาย" = ready-to-sell
    grade = f("grade")
    note = f("note", val_pat=r'[^"]{0,800}')
    bedroom = fn("bedroom")
    bathroom = fn("bathroom")

    # JSON-LD for name + image (cleaner than digging through escaped stream)
    m_ld = re.search(r'"@type":"Product","name":"([^"]+)".*?"image":"([^"]+)"', h, re.S)
    name = img = ""
    if m_ld:
        name = m_ld.group(1)
        img = m_ld.group(2).replace("\\/", "/")

    # Area in sqm
    try:
        rai_f = float(rai); ngan_f = float(ngan); wa_f = float(wa)
        sqm_land = rai_f * 1600 + ngan_f * 400 + wa_f * 4
    except: sqm_land = 0
    try:
        sqm_usable = float(usable)
    except: sqm_usable = 0
    try:
        sqm_area = float(area_m)
    except: sqm_area = 0

    # For pure land: sqm_land. For buildings: usable area is interior floor.
    # Land+building: prefer rai/ngan/wa (lot size).
    if asset_type in ("ห้องชุด", "อาคารชุด"):
        sqm = sqm_usable  # condo interior
    else:
        sqm = sqm_land or sqm_area or sqm_usable

    try:
        lat_f = float(lat) if lat else None
        lng_f = float(lng) if lng else None
    except:
        lat_f = lng_f = None

    try:
        price_thb = int(float(price))
    except:
        price_thb = 0

    if not price_thb:
        return None

    return {
        "id": bam_id,
        "name": name,
        "asset_type": asset_type,
        "img": img,
        "price_thb": price_thb,
        "lat": lat_f, "lng": lng_f,
        "province": province, "district": district,
        "sqm": sqm,
        "sqm_land": sqm_land,
        "sqm_usable": sqm_usable,
        "state": state, "grade": grade,
        "bedroom": int(float(bedroom)) if bedroom else None,
        "bathroom": int(float(bathroom)) if bathroom else None,
        "note": note[:500],
        "url": f"https://www.bam.co.th/th/npa/property/{bam_id}",
    }

if __name__ == "__main__":
    ids = [r["id"] for r in json.load(open("/tmp/bam_ids.json"))]
    print(f"fetching detail for {len(ids)} BAM properties...", file=sys.stderr)
    out = []
    errs = 0
    for i, bid in enumerate(ids):
        url = f"https://www.bam.co.th/th/th/npa/property/{bid}"
        h = via_relay(url, timeout=40)
        if not h or len(h) < 50000:
            errs += 1; continue
        parsed = parse_detail(h, bid)
        if parsed:
            out.append(parsed)
        if i and i % 25 == 0:
            json.dump(out, open("/tmp/bam_full.json","w"), ensure_ascii=False)
            print(f"  {i}/{len(ids)} done (parsed: {len(out)}, errs: {errs})", file=sys.stderr)
        time.sleep(0.3)
    json.dump(out, open("/tmp/bam_full.json","w"), ensure_ascii=False)
    print(f"\ndone. parsed {len(out)}/{len(ids)} (errs {errs})", file=sys.stderr)
    from collections import Counter
    ats = Counter(r.get("asset_type") for r in out)
    print(f"asset types: {ats.most_common()}", file=sys.stderr)
    provs = Counter(r.get("province") for r in out)
    print(f"top provinces: {provs.most_common(10)}", file=sys.stderr)
