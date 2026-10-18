"""Price watch: re-check watched listings and record every asking-price change.

docs/price_watch.json holds one entry per listing URL with a dated price
history. Each run fetches the page (through the relay), reads the current
asking price from the listing's structured data (schema.org Offer — Redfin,
Lazudi, SUUMO-style pages) and appends an entry when it changed. Delisted
pages (HTTP 404/410) are recorded as "Off market". It never removes watches.

Usage:
  python3 scripts/price_watch.py                 # check every watch
  python3 scripts/price_watch.py add <url> [label]   # start watching a URL
"""
import json, os, re, subprocess, sys, urllib.parse
from datetime import date

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PATH = os.path.join(ROOT, "docs", "price_watch.json")
RELAY = "https://landrelay.flag-theory.workers.dev"

def fetch(url):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    p = subprocess.run(["curl", "-sk", "-m", "45", "-w", "\n@@%{http_code}", api],
                       capture_output=True, text=True, timeout=55)
    body, _, code = p.stdout.rpartition("\n@@")
    return code.strip(), body

def current_price(html):
    for b in re.findall(r'application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            d = json.loads(b)
        except Exception:
            continue
        for item in (d if isinstance(d, list) else [d]):
            if not isinstance(item, dict): continue
            t = str(item.get("@type"))
            if "RealEstateListing" in t or "Product" in t or "SingleFamilyResidence" in t:
                off = item.get("offers") or {}
                if isinstance(off, list): off = off[0] if off else {}
                try:
                    return int(float(off.get("price")))
                except Exception:
                    pass
    # Japanese portals (Yahoo!不動産 / SUUMO): price in 万円 → yen
    m = re.search(r'buildingPrice&quot;:(\d+)', html) or re.search(r'"buildingPrice"\s*:\s*(\d+)', html) or \
        re.search(r'販売価格[^0-9]{0,40}([\d,]+)\s*万円', html)
    if m: return int(m.group(1).replace(",", "")) * 10000
    # SUUMO and other Japanese pages: "価格 … 1億2,000万円" / "980万円" in the visible text
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style).*?</\1>", "", html, flags=re.S)))
    m = re.search(r"価格[^0-9億]{0,30}(?:(\d+)億)?\s*([\d,]+)?\s*万円", text)
    if m and (m.group(1) or m.group(2)):
        return int(m.group(1) or 0) * 100_000_000 + int((m.group(2) or "0").replace(",", "")) * 10000
    m = re.search(r'"listingPrice"\s*:\s*\{[^}]*"amount"\s*:\s*(\d+)', html) or \
        re.search(r'"price"\s*:\s*"?(\d{5,})"?', html)
    return int(m.group(1)) if m else None

def main():
    pw = json.load(open(PATH)) if os.path.exists(PATH) else {"schema": "price_watch_v1", "watches": {}}
    today = date.today().isoformat()
    if len(sys.argv) > 2 and sys.argv[1] == "add":
        url = sys.argv[2]
        pw["watches"].setdefault(url, {"label": sys.argv[3] if len(sys.argv) > 3 else url,
                                       "added": today, "history": []})
    changes = 0
    for url, w in pw["watches"].items():
        code, html = fetch(url)
        hist = w.setdefault("history", [])
        last = hist[-1]["price"] if hist else None
        if code in ("404", "410"):
            if not hist or hist[-1].get("event") != "Off market":
                hist.append({"date": today, "price": last, "event": "Off market"}); changes += 1
        else:
            price = current_price(html) if code == "200" else None
            if price and price != last:
                ev = "Listed" if last is None else ("Price cut" if price < last else "Price increase")
                hist.append({"date": today, "price": price, "event": ev}); changes += 1
                print(f"{w.get('label', url)}: {last} → {price}", file=sys.stderr)
            elif not price:
                print(f"{w.get('label', url)}: could not read a price (HTTP {code})", file=sys.stderr)
        w["last_checked"] = today
    json.dump(pw, open(PATH, "w"), ensure_ascii=False, indent=1)
    print(f"checked {len(pw['watches'])} watches · {changes} changes", file=sys.stderr)

if __name__ == "__main__":
    main()
