"""Coldwell Banker Costa Rica (coldwellbankercostarica.com): land and houses -> listings.json.

The site's property sitemaps list every listing. Takes land and single-family homes for sale
(not rentals, condos or commercial), skips the San José suburbs, and reads each listing page
through the relay: title, town / province, price, acres, bedrooms, map position (the page's
Google Maps embed), status and photos. Rows carry rb 'src:coldwell-cr' (re-running replaces
them), get the Central America 2-of-3 signals (big land / Pacific view / waterfall) and the
usual coast / ski distances.

Pages already read are kept in data/raw/coldwell_cr_cache.json.gz, so a daily run only reads new
listings (delete the file to re-read everything, e.g. to pick up price changes).
Usage: python3 scripts/coldwell_cr.py [max_listings]
"""
import gzip, html, json, os, re, subprocess, sys, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ca_signals import signals, FOREIGN

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PATH = os.path.join(ROOT, "docs", "listings.json")
RELAY = "https://landrelay.flag-theory.workers.dev/?url="
BASE = "https://www.coldwellbankercostarica.com"
SRC = "src:coldwell-cr"
CACHE = os.path.join(ROOT, "data", "raw", "coldwell_cr_cache.json.gz")
SUBURBS = re.compile(r"-in-(santa-ana|escazu|curridabat|tres-rios|alajuela|heredia|san-jose|moravia|la-guacima|belen|"
                     r"santo-domingo|cartago|rohrmoser|sabana|pavas|guadalupe|ciudad-colon|san-rafael|san-pablo|"
                     r"barva|coronado|desamparados|lindora|pozos|brasil-de-mora|piedades)/", re.I)

THROTTLED = "THROTTLED"

def get(url, tries=4):
    """Direct first, the relay as a fallback. The site answers bursts with 429 'Too Many Requests':
    back off and, if it persists, return THROTTLED so the page is retried on a later run."""
    for i in range(tries):
        for via in ([], [RELAY + urllib.parse.quote(url, safe="")]):
            target = via[0] if via else url
            out = subprocess.run(["curl", "-s", "--max-time", "60", "-A", "Mozilla/5.0 (land-app)", target],
                                 capture_output=True, text=True).stdout
            if "Too Many Requests" in out[:600]: continue
            if len(out) > 5000: return out
        time.sleep(20 * (i + 1))
    return THROTTLED

def urls():
    out = []
    for i in range(1, 30):
        s = get(f"{BASE}/sitemap-properties.xml?page={i}")
        locs = re.findall(r"<loc>([^<]+)</loc>", s)
        if not locs: break
        out += locs
    keep = [u for u in dict.fromkeys(out) if "/es/" not in u and "to-rent" not in u
            and re.search(r"/property/(\d+-bed-)?(land|single-family-homes)-for-sale-in-", u) and not SUBURBS.search(u)]
    return keep

def text(x):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", x)).split())

def parse(u, s):
    if not s: return None
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", s, re.S); h4 = re.search(r'<h4 class="f-20[^"]*"[^>]*>(.*?)</h4>', s, re.S)
    price = re.search(r'<h3 class="f-28[^"]*"[^>]*>\s*\$([\d,]+)', s)
    ll = re.search(r"maps\?q=(-?\d+\.\d+),(-?\d+\.\d+)", s) or re.search(r"q=(-?\d{1,2}\.\d{3,}),(-?\d{2,3}\.\d{3,})", s)
    acres = re.search(r"([\d,.]+)\s*Acres", s)
    beds = re.search(r"(\d+)\s*Bed", text(s[:200000])) if "single-family" in u else None
    status = re.search(r'class="status-inner[^"]*"[^>]*>(.*?)</div>', s, re.S)
    pics = list(dict.fromkeys(re.findall(r"https://s3\.amazonaws\.com/propertybase-clients/[^\"'\s]+?/(?:hires|midres)/[^\"'\s/]+?\.(?:jpe?g|png|webp)", s)))
    pics = [p for p in pics if "/hires/" in p] or pics
    desc = re.search(r'<meta name="description" content="([^"]*)"', s)
    body = re.search(r'(?:id="description"|class="desc[^"]*")[^>]*>(.*?)</div>', s, re.S)
    if not (price and ll): return None
    return {"url": u, "title": text(h1.group(1)) if h1 else "", "place": text(h4.group(1)) if h4 else "",
            "usd": int(price.group(1).replace(",", "")), "lat": float(ll.group(1)), "lon": float(ll.group(2)),
            "acres": float(acres.group(1).replace(",", "")) if acres else None, "beds": int(beds.group(1)) if beds else None,
            "status": text(status.group(1)) if status else "", "imgs": pics[:12],
            "desc": (text(body.group(1)) if body else "") or (html.unescape(desc.group(1)) if desc else "")}

def main(cap):
    cache = json.load(gzip.open(CACHE, "rt")) if os.path.exists(CACHE) else {}
    cache = {u: v for u, v in cache.items() if v is not None}     # pages that failed earlier get another try
    todo = [u for u in urls() if u not in cache][:cap]
    print(f"coldwell-cr: {len(todo)} pages to read ({len(cache)} cached)", file=sys.stderr)
    def one(u):
        s = get(u)
        time.sleep(1.5)                       # be gentle: the site rate-limits
        return u, (THROTTLED if s == THROTTLED else parse(u, s))
    throttled = 0
    with ThreadPoolExecutor(max_workers=2) as ex:
        for i, (u, r) in enumerate(ex.map(one, todo), 1):
            if r == THROTTLED: throttled += 1; continue      # not cached: retried next run
            cache[u] = r
            if i % 200 == 0:
                json.dump(cache, gzip.open(CACHE, "wt")); print(f"  {i}/{len(todo)}", file=sys.stderr)
    json.dump(cache, gzip.open(CACHE, "wt"))
    if throttled: print(f"coldwell-cr: {throttled} pages throttled, will retry next run", file=sys.stderr)
    d = [r for r in json.load(open(PATH)) if r.get("rb", "").split("+")[0] != SRC]
    have = {r.get("u") for r in d}
    rows = []
    for u, c in cache.items():
        if not c or u in have or re.search(r"sold|under contract|reserved|vendid", c.get("status", ""), re.I): continue
        if not (8 < c["lat"] < 11.5 and -86.2 < c["lon"] < -82.4): continue        # Costa Rica only
        land = "/land-for-sale" in u or re.search(r"-land-for-sale", u)
        ac = c.get("acres") or 0; m2 = int(ac * 4046.86) if ac else None
        town = c["place"].split(",")[0].strip() if c["place"] else re.sub(r".*-for-sale-in-|/\d+$", "", u).replace("-", " ").title()
        sig, pkm = signals(f"{c['title']} {c['desc']}", c["lat"], c["lon"], ac, "Costa Rica")
        perks = []
        if "big" in sig: perks.append(f"🌳 {ac:,.0f} acres")
        if "pacific" in sig: perks.append(f"🌊 Pacific Ocean view ({pkm:.0f} km to the coast)")
        if "waterfall" in sig: perks.append("💧 waterfall on or by the land")
        row = {"cf": "Costa Rica", "rg": (c["place"].split(",")[-1].strip() if c["place"] else "Costa Rica"), "a": town[:40],
               "tp": "land" if land else "house", "t": "land" if land else "house", "ac": round(ac, 3) if ac else None,
               "m2": m2 if land else None, "plot_m2": m2, "beds": c.get("beds"), "usd": c["usd"],
               "upm": round(c["usd"] / m2, 2) if (land and m2) else None, "cur": "USD", "lp": str(c["usd"]),
               "lat": round(c["lat"], 5), "lon": round(c["lon"], 5), "v": "sea_view" if "pacific" in sig else "",
               "imgs": c.get("imgs") or [], "u": u, "name": c["title"][:180], "desc": (c.get("desc") or "")[:600],
               "perks": perks, "r": 45 + 10 * len(sig), "rb": SRC + (f"+signals:{'/'.join(sig)}" if sig else ""),
               "foreign_note": FOREIGN["Costa Rica"], "source": "Coldwell Banker Costa Rica"}
        if len(sig) >= 2: row.update({"ca_signals": sig, "pacific_km": pkm})
        rows.append(row)
    json.dump(d + rows, open(PATH, "w"), separators=(",", ":"), ensure_ascii=False)
    print(f"coldwell-cr: {len(rows)} listings ({sum(1 for r in rows if r['tp'] == 'land')} land); "
          f"{sum(1 for r in rows if r.get('ca_signals'))} meet the Central America 2-of-3", file=sys.stderr)
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "global_distances.py"), PATH], check=True)

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 100000)
