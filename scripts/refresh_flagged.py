"""Daily price-watch on the FLAGGED set — the seller-caving loop.

Re-fetches the current asking price for every nominee-flagged (company-held)
Thai listing, updates docs/listings.json, then lets snapshot_history detect
any drop. Bounded (~260 relay fetches, ~5-8 min) so it's safe to run daily,
unlike the full weekly re-scrape.

Emits nothing new; mutates listings.json prices in place and prints a
summary of any drops caught.
"""
import json, re, sys, time
sys.path.insert(0, "/home/user/land-app/scripts")
from nominee_scan import via_relay

LIST = "/home/user/land-app/docs/listings.json"

def current_price(url):
    """Re-read the asking price (USD) off a FazWaz listing title. Returns
    None on any fetch/parse failure — callers leave the price untouched
    (never guess a delisting from text; snapshot_history handles that when
    a URL truly disappears from the dataset)."""
    body = via_relay(url)
    if not body or len(body) < 40000:
        return None
    m = re.search(r'for\s*\$([\d,]+)\s*\|', body)
    return int(m.group(1).replace(",", "")) if m else None

def main():
    d = json.load(open(LIST))
    flagged = [r for r in d if r.get("nominee") and "fazwaz.com" in (r.get("u") or "")]
    print(f"re-checking {len(flagged)} flagged listings", file=sys.stderr)

    changed = drops = 0
    for i, r in enumerate(flagged):
        price = current_price(r["u"])
        if price and price != r.get("usd"):
            old = r.get("usd")
            r["usd"] = price
            if r.get("m2"):
                raw = price / r["m2"]
                r["upm"] = round(raw, 3 if raw < 1 else (2 if raw < 10 else 1))
            changed += 1
            if old and price < old:
                drops += 1
                print(f"  DROP {r['rg']}: ${old:,} -> ${price:,} ({round((1-price/old)*100)}%) {r['u']}", file=sys.stderr)
        if (i + 1) % 40 == 0:
            json.dump(d, open(LIST, "w"), separators=(",", ":"))
            print(f"  {i+1}/{len(flagged)}", file=sys.stderr)
        time.sleep(0.25)

    json.dump(d, open(LIST, "w"), separators=(",", ":"))
    print(f"done: {changed} price changes, {drops} drops", file=sys.stderr)

if __name__ == "__main__":
    main()
