"""Encuentra24: Costa Rica land, farms and homes for sale.

Listing pages (the national category lists) are open; detail pages and the
province filters sit behind Cloudflare, so everything comes off the list tiles:
id, title, district, short description, price (US$ or colones), area, first photo.
Emits /tmp/encuentra24_cr.json for encuentra24_cr_merge.py.

Usage: python3 scripts/encuentra24_cr_scrape.py [max_pages_per_category]
"""
import html, json, re, subprocess, sys, time, urllib.parse

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
RELAY = "https://landrelay.flag-theory.workers.dev"
OUT = "/tmp/encuentra24_cr.json"
BASE = "https://www.encuentra24.com/costa-rica-en/"
CATS = {"real-estate-for-sale-lots-land": "land", "real-estate-for-sale-farms": "farm",
        "real-estate-for-sale-houses-homes": "house"}
CRC_USD = 1 / 505          # colones -> US$ (approx.)

def get(url):
    for attempt in range(3):
        # the relay is fast; direct requests get Cloudflare-throttled after a few pages
        cmd = ["curl", "-sk", "-m", "45", f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"] if attempt != 1 else \
              ["curl", "-sL", "-m", "40", "-A", UA, url]
        try:
            body = subprocess.run(cmd, capture_output=True, text=True, timeout=50).stdout
        except Exception:
            body = ""
        if "d3-ad-tile__title" in body:
            return body
        time.sleep(4 * (attempt + 1))
    return ""

def text(fragment):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment or ""))).strip()

def field(tile, cls):
    m = re.search(r'class="d3-ad-tile__' + cls + r'[^"]*"[^>]*>(.*?)</(?:div|span|a|p|strong|h2|h3)>', tile, re.S)
    return text(m.group(1)) if m else ""

def parse(page, kind):
    out = []
    for t in re.split(r'<div class="d3-ad-tile[ "]', page)[1:]:
        m = re.search(r'href="(/costa-rica-en/real-estate-for-sale-[^"]+/(\d+))"', t)
        if not m: continue
        price_txt = field(t, "price")
        pm = re.search(r"([$₡])\s?([\d,\.]+)", price_txt)
        if not pm: continue
        amount = float(pm.group(2).replace(",", ""))
        usd = amount if pm.group(1) == "$" else amount * CRC_USD
        details = [text(x) for x in re.findall(r'class="d3-ad-tile__details-item[^"]*"[^>]*>(.*?)</(?:div|span|li)>', t, re.S)]
        m2 = None
        for d in details:
            a = re.search(r"([\d,\.]+)\s*m\s*2", d)
            if a:
                m2 = float(a.group(1).replace(",", "")); break
        beds = next((int(re.search(r"\d+", d).group()) for d in details if re.search(r"\d+\s*(?:bed|hab|dorm)", d, re.I)), None)
        img = re.search(r'data-src="(https://photos\.encuentra24\.com/[^"]+)"', t)
        out.append({"id": m.group(2), "url": "https://www.encuentra24.com" + m.group(1), "kind": kind,
                    "title": field(t, "title"), "location": field(t, "location"), "desc": field(t, "short-description"),
                    "usd": round(usd), "cur": "USD" if pm.group(1) == "$" else "CRC", "amount": amount,
                    "m2": m2, "beds": beds, "details": details, "img": img.group(1) if img else None})
    return out

def main(max_pages):
    rows = {}
    for cat, kind in CATS.items():
        first = get(BASE + cat)
        pages = max([int(x) for x in re.findall(r'data-page="(\d+)"', first)] or [1])
        pages = min(pages, max_pages)
        for p in range(1, pages + 1):
            body = first if p == 1 else get(f"{BASE}{cat}.{p}")
            got = parse(body, kind)
            for r in got: rows.setdefault(r["id"], r)
            if p % 20 == 0:
                print(f"  {cat}: page {p}/{pages} · {len(rows)} rows", file=sys.stderr)
                json.dump(list(rows.values()), open(OUT, "w"), ensure_ascii=False)
            time.sleep(0.5)
        print(f"{cat}: done, {len(rows)} rows total", file=sys.stderr)
    json.dump(list(rows.values()), open(OUT, "w"), ensure_ascii=False)
    print(f"TOTAL {len(rows)} -> {OUT}", file=sys.stderr)

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 10_000)
