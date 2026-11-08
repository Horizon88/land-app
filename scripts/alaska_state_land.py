"""Alaska DNR state land sales -> listings.json.

Reads the parcel list at dnr.alaska.gov/mlw/landsales/parcels (every parcel the
state is currently offering: over-the-counter, which anyone can buy, and
auctions, which are Alaska-residents only), then each parcel's detail page for
its location text, legal description (MTRS), access, utilities and photos.
The MTRS section is turned into coordinates with BLM's PLSS service (section
centroid, so pins are good to ~1 km). Distances and the sea-view score are then
computed like every other listing.

Re-run it whenever DNR adds parcels (the second OTC round opens in December).
Rows carry rb 'src:ak-dnr' and are replaced on each run.

Brochure mode (--brochure): before the over-the-counter list is published, read
every parcel of the year's auction brochure (PDF on the DNR site): subdivision,
location, access, utilities, legal description, acres and minimum bid. Parcels
that don't sell at auction become over-the-counter parcels, first at +30%, then
+15%, then at the minimum bid. Rows carry rb 'src:ak-dnr-brochure'.

Usage: python3 scripts/alaska_state_land.py [--brochure BROCHURE_FILE_ID] (57 = auction #498)
"""
import html, json, os, re, subprocess, sys, time, urllib.parse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PATH = os.path.join(ROOT, "docs", "listings.json")
BASE = "https://dnr.alaska.gov"
SRC = "src:ak-dnr"
PLSS = "https://gis.blm.gov/arcgis/rest/services/Cadastral/BLM_Natl_PLSS_CadNSDI/MapServer"
MERIDIAN = {"S": "28", "F": "13", "C": "12", "K": "44", "U": "45"}   # Seward, Fairbanks, Copper River, Kateel River, Umiat

def get(url, tries=3):
    for i in range(tries):    # the DNR site sometimes returns an empty page; retry
        out = subprocess.run(["curl", "-sL", "--max-time", "40", "-A", "Mozilla/5.0", url],
                             capture_output=True, text=True).stdout
        if len(out) > 2000 or "gis.blm.gov" in url: return out
        time.sleep(3 * (i + 1))
    return out

def text(s):
    s = re.sub(r"<script.*?</script>|<style.*?</style>", "", s, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())

def section_centroid(mtrs):
    """'S004S014W36' -> (lat, lon) of that section's centroid, or None."""
    m = re.match(r"([SFCKU])(\d{3})([NS])(\d{3})([EW])(\d{2})", mtrs or "")
    if not m: return None
    mer, t, td, r, rd, sec = m.groups()
    plssid = f"AK{MERIDIAN[mer]}{t}0{td}{r}0{rd}0"
    q = urllib.parse.urlencode({"where": f"PLSSID='{plssid}' AND FRSTDIVNO='{int(sec)}'", "outFields": "FRSTDIVID",
                                "returnGeometry": "true", "outSR": "4326", "f": "json"})
    try:
        feats = json.loads(get(f"{PLSS}/2/query?{q}")).get("features") or []
        ring = feats[0]["geometry"]["rings"][0]
        return round(sum(p[1] for p in ring) / len(ring), 5), round(sum(p[0] for p in ring) / len(ring), 5)
    except Exception:
        pass
    # unsurveyed (protracted) townships have no section polygons: place the section on the
    # township's 6x6 grid (1-6 run east->west along the top row, 7-12 back west->east, ...)
    q = urllib.parse.urlencode({"where": f"PLSSID='{plssid}'", "outFields": "PLSSID", "returnGeometry": "true",
                                "outSR": "4326", "f": "json"})
    try:
        ring = json.loads(get(f"{PLSS}/1/query?{q}"))["features"][0]["geometry"]["rings"][0]
    except Exception:
        return None
    w, e = min(p[0] for p in ring), max(p[0] for p in ring)
    so, n = min(p[1] for p in ring), max(p[1] for p in ring)
    row, k = divmod(int(sec) - 1, 6)
    col = 5 - k if row % 2 == 0 else k
    return round(n - (row + 0.5) / 6 * (n - so), 5), round(w + (col + 0.5) / 6 * (e - w), 5)

def field(t, label, stop):
    m = re.search(label + r"\s+(.*?)\s+(?:" + stop + r")\b", t)
    return m.group(1).strip() if m else ""

MER_NAMES = {"Seward": "S", "Fairbanks": "F", "Copper River": "C", "Kateel River": "K", "Umiat": "U"}
SKIP_HEADS = {"CONTINUED", "NUMBER(S)", "POTENTIAL CONTAMINATION.", "ONLINE RESOURCES"}
WATER = re.compile(r"\b(lake|river|creek|ocean|bay|inlet|cove|sound|beach|waterfront|shore)\b", re.I)

def brochure(file_id):
    """Parse an auction brochure PDF into listing rows."""
    tmp = f"/tmp/ak_brochure_{file_id}"
    subprocess.run(["curl", "-sL", "--max-time", "120", "-A", "Mozilla/5.0", "-o", tmp + ".pdf",
                    f"{BASE}/mlw/landsales/brochure/file/{file_id}/brochure"], check=True)
    subprocess.run(["pdftotext", "-layout", tmp + ".pdf", tmp + ".txt"], check=True)
    L = open(tmp + ".txt").read().split("\n")
    auction = (re.search(r"Auction\s*#?(\d{3})", " ".join(L[:200])) or [None, "?"])[1]
    otc_dates = re.findall(r"(?:1st OTC Offering|General OTC Offering)\s+Begins (10:00 a\.m\., \w+ \d+, \d{4})", " ".join(L))
    heads = [i for i, l in enumerate(L) if re.fullmatch(r"[A-Z][A-Z0-9 '&\-./()]{4,44}", l.strip())
             and "PARCEL" not in l and "REGION" not in l and l.strip() not in SKIP_HEADS]
    start = next(i for i, l in enumerate(L) if l.strip().endswith("REGION") and i > 1900)
    blocks = [(h, nxt) for h, nxt in zip(heads, heads[1:] + [len(L)]) if h > start and L[h].strip() != "ONLINE RESOURCES"]
    rows, region = [], ""
    for h, end in blocks:
        name = L[h].strip().title().replace("Rrcs", "RRCS").replace("Ii", "II")
        chunk = L[h:end]
        regs = [l.strip() for l in L[max(start, h - 400):h] if l.strip().endswith("REGION")]
        if regs: region = regs[-1].title()
        flat = " ".join(" ".join(l.split()) for l in chunk)
        mflat = " ".join(re.sub(r"\b(MTRS|Survey and|Rights-of-Way)\b", " ", flat).split())   # left-column labels split sentences
        def sect(label, nxt):
            m = re.search(label + r"\s+(.*?)\s+(?:" + nxt + r")\s", flat)
            return m.group(1) if m else ""
        location = sect("Location", "Access")
        access = sect("Access", "Utilities|Local")
        utilities = sect("Utilities", "Local|Fire")
        m = re.search(r"Section(?:s|\(s\))?\s+(\d+)[^T]{0,60}?Townships?\s+(\d+)\s+(North|South)[^R]{0,40}?Ranges?\s+(\d+)[^EW]{0,20}?(East|West)[^M]{0,80}?"
                      r"(Seward|Fairbanks|Copper River|Kateel River|Umiat)\s+Meridian", mflat)
        if not m: print(f"  {name}: no MTRS", file=sys.stderr); continue
        sec, t, td, r, rd, mer = m.groups()
        mtrs = f"{MER_NAMES[mer]}{int(t):03d}{td[0]}{int(r):03d}{rd[0]}{int(sec):02d}"
        ll = section_centroid(mtrs)
        if not ll: print(f"  {name}: no coordinates ({mtrs})", file=sys.stderr); continue
        for l in chunk:
            pm = re.match(r"^\s*(\d{3,4})\s+(\d{5,6})\s+.*?([\d,]+\.\d+)\s+\$([\d,]+)\s*$", l)
            if not pm: continue
            pn, adl, acres, bid = pm.group(1), pm.group(2), float(pm.group(3).replace(",", "")), int(pm.group(4).replace(",", ""))
            m2 = int(acres * 4046.86)
            remote = "RRCS" in name or re.search(r"float ?plane|boat|snowmachine|fly-in|aircraft|winter trail", access, re.I)
            warn = ["auction parcel: buyable over-the-counter only if it didn't sell at auction (check the list on " +
                    (otc_dates[0] if otc_dates else "the OTC date") + ")"]
            if remote: warn.append("remote: no road (plane, boat or snowmachine)")
            if "wetland" in flat.lower(): warn.append("may contain wetlands (Army Corps permit to build on them)")
            if "no municipal water" in flat.lower(): warn.append("no public water or sewer: well and septic")
            water = sorted(set(w.lower() for w in WATER.findall(location + " " + name)))
            rows.append({
                "cf": "USA", "state": "AK", "rg": f"{region.replace(' Region', '')} AK (state land)", "a": name[:40], "tp": "land",
                "t": f"State of Alaska auction #{auction} parcel · minimum bid", "ac": acres, "m2": m2, "usd": bid,
                "upm": round(bid / m2, 3), "cur": "USD", "lp": str(bid), "lat": ll[0], "lon": ll[1], "loc_approx": True, "v": "",
                "imgs": [], "u": f"{BASE}/mlw/landsales/parcels/details/{auction}-{pn}",
                "name": f"{name} parcel {pn}: {acres:g} acres, minimum bid ${bid:,}"[:180],
                "desc": " ".join(x for x in (location, access, utilities) if x)[:600],
                "perks": [p for p in (f"💧 near {', '.join(water)}" if water else "",
                                      "🏛 State of Alaska land: clean title straight from the state") if p],
                "warn": warn, "mtrs": mtrs, "adl": adl, "r": 35, "rb": f"{SRC}-brochure+auction{auction}",
                "foreign_note": "Auction: Alaska residents only. Unsold parcels go over-the-counter, open to anyone, first come first served.",
            })
        print(f"  {name}: {sum(1 for x in rows if x['a'] == name[:40])} parcels @ {ll}", file=sys.stderr)
    return rows

def main_brochure(file_id):
    rows = brochure(file_id)
    live = {r["u"] for r in json.load(open(PATH)) if (r.get("rb") or "").startswith(SRC + "+")}
    rows = [r for r in rows if r["u"] not in live]          # the live OTC list wins
    tag = f"{SRC}-brochure"
    d = [r for r in json.load(open(PATH)) if tag not in (r.get("rb") or "")]
    json.dump(d + rows, open(PATH, "w"), separators=(",", ":"), ensure_ascii=False)
    print(f"Alaska brochure #{file_id}: {len(rows)} parcels", file=sys.stderr)
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "global_distances.py"), PATH], check=True)

def main():
    page = get(f"{BASE}/mlw/landsales/parcels/")
    cards = re.findall(r"<section[^>]*data-parcel[^>]*>.*?</section>", page, re.S)
    rows = []
    for c in cards:
        a = dict(re.findall(r'data-([a-z]+)="([^"]*)"', c[:800]))
        pid = f"{a['auction']}-{a['parcel']}"
        url = f"{BASE}/mlw/landsales/parcels/details/{pid}"
        d = get(url); t = text(d)
        mtrs = (re.search(r"\(MTRS\):\s*([SFCKU]\d{3}[NS]\d{3}[EW]\d{2})", t) or [None, None])[1]
        ll = section_centroid(mtrs)
        if not ll:
            print(f"  {pid}: no coordinates (MTRS {mtrs})", file=sys.stderr); continue
        acres, usd = float(a["acres"]), int(float(a["price"]))
        location = field(t, "Location", "Meridian")
        access = field(t, "Access Details", "Utilities")
        utilities = field(t, "Utilities", "Local Government")
        avail = (re.search(r"Available:\s*([\d/]+ [\d:]+ [AP]M)", t) or [None, ""])[1]
        road = "No Road Access" not in text(c)
        otc = a.get("program") == "OTC"
        ag = "Agricultural" in a.get("subd", "")
        imgs = [u for u in dict.fromkeys(re.findall(r"https://dnr\.alaska\.gov/mlw/cdn/img/landsales/subdivisions/[^\"'/]+\.(?:jpg|jpeg|png)", d))]
        warn = []
        if not otc: warn.append("auction: Alaska residents only")
        if ag: warn.append("agricultural covenant: land must stay in farm use (a house for the owner is allowed)")
        if not road: warn.append("no road access")
        if "no municipal water" in t.lower() or "no public water" in t.lower(): warn.append("no public water or sewer: well and septic")
        m2 = int(acres * 4046.86)
        rows.append({
            "cf": "USA", "state": "AK", "rg": f"{a.get('region', '')} AK (state land)", "a": a.get("subd", "")[:40], "tp": "land",
            "t": f"State of Alaska {'over-the-counter' if otc else 'auction'} parcel · " + ("road access" if road else "no road access"),
            "ac": acres, "m2": m2, "usd": usd, "upm": round(usd / m2, 3), "cur": "USD", "lp": str(usd),
            "lat": ll[0], "lon": ll[1], "loc_approx": True, "v": "", "imgs": imgs[:8], "u": url,
            "name": f"Parcel {pid}, {a.get('subd', '')}: {acres:g} acres for ${usd:,}"[:180],
            "desc": " ".join(x for x in (location, access, utilities) if x)[:600],
            "perks": [p for p in ("🏛 bought straight from the State of Alaska at appraised value" if otc else "",
                                  f"📅 on sale from {avail}" if avail else "", "🛣 road access" if road else "") if p],
            "warn": warn, "mtrs": mtrs, "adl": a.get("adl"), "r": 45 if otc else 30,
            "rb": f"{SRC}+{'otc' if otc else 'auction'}",
            "foreign_note": "Over-the-counter state parcels are open to anyone, including non-residents; auctions are Alaska residents only.",
        })
        print(f"  {pid}: {acres:g} ac ${usd:,} {'OTC' if otc else 'auction'} @ {ll}", file=sys.stderr)
    d = [r for r in json.load(open(PATH)) if not (r.get("rb") or "").startswith(SRC + "+")]
    json.dump(d + rows, open(PATH, "w"), separators=(",", ":"), ensure_ascii=False)
    print(f"Alaska state land: {len(rows)} parcels from {len(cards)} on the DNR list", file=sys.stderr)
    if rows:
        subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "global_distances.py"), PATH], check=True)

if __name__ == "__main__":
    if "--brochure" in sys.argv: main_brochure(sys.argv[sys.argv.index("--brochure") + 1])
    else: main()
