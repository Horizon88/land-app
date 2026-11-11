"""Snapshot pipeline: track first_seen date + price history per listing URL.

Runs after all scrapers/merges finish. Reads docs/listings.json + data/history.json,
updates history for every URL in current listings:
  - if URL is new -> record today as first_seen
  - if the asking price changed vs the latest history entry -> append (date, usd, lp, cur).
    Prices are compared in the listing's own currency, so exchange-rate moves on
    yen / baht / euro listings don't show up as fake price cuts.
  - if URL disappeared -> mark delisted (do NOT delete — it may be sold or withdrawn)

Then enriches listings.json with derived fields:
  - first_seen  (ISO date)
  - days_on_market: the larger of what the source reports (dom_src, e.g. Redfin's
    MLS days on market) and the days since we first saw it
  - price_drops: list of {date, from, to, pct}
  - total_drop_pct (cumulative drop from the first price we saw)

Distress (forced-sale) points from time on market and price drops, replacing the
points this script added on its previous run, so re-running never double-counts:
  - on market >= 90d  -> +8,  >= 180d -> +18,  >= 365d -> +30
  - price drop >= 5%  -> +8,  >= 10%  -> +18,  >= 20%  -> +30
Capped at 100.

Usage: python3 scripts/snapshot_history.py [--date YYYY-MM-DD] [--listings FILE]
  --date / --listings replay an old copy of listings.json (from git) into the
  history only, to backfill first_seen and price changes.
"""
import json, os, sys
from datetime import date

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIST = os.path.join(ROOT, "docs", "listings.json")
HIST = os.path.join(ROOT, "data", "history.json")
OURS = ("on-market ≥", "price dropped ")       # breakdown labels this script owns

def load_json(p, default):
    if not os.path.exists(p): return default
    try: return json.load(open(p))
    except Exception: return default

def num(x):
    try: return float(str(x).replace(",", ""))
    except Exception: return None

def same_price(a, r):
    """Is the listing's current price the same as history entry a?"""
    cur = r.get("cur") or ""
    if a.get("cur") == cur and num(a.get("lp")) and num(r.get("lp")):
        return num(a["lp"]) == num(r["lp"])
    return a.get("usd") == r.get("usd")

def native_drop(a, b):
    """% drop from entry a to b in the listing's currency (None if not a drop)."""
    if a.get("cur") == b.get("cur") and num(a.get("lp")) and num(b.get("lp")):
        x, y = num(a["lp"]), num(b["lp"])
    else:
        x, y = a.get("usd"), b.get("usd")
    if x and y and y < x: return round((x - y) / x * 100, 1)
    return None

def update(hist, listings, today):
    new_urls = changes = 0
    seen = set()
    for r in listings:
        u = r.get("u")
        if not u: continue
        seen.add(u)
        entry = {"date": today, "usd": r.get("usd"), "lp": r.get("lp") or str(r.get("usd") or ""), "cur": r.get("cur", "")}
        h = hist.get(u)
        if not h:
            hist[u] = {"first_seen": today, "last_seen": today, "history": [entry]}
            new_urls += 1
            continue
        if today < h["first_seen"]: continue          # replaying an older snapshot than we hold
        h["last_seen"] = max(h.get("last_seen", today), today)
        h.pop("delisted", None)
        last = h["history"][-1] if h["history"] else None
        if not last or not same_price(last, r):
            h["history"].append(entry); changes += 1
    for u, h in hist.items():
        if u not in seen and not h.get("delisted") and h.get("last_seen", "") < today:
            h["delisted"] = today
    return new_urls, changes

def enrich(hist, listings, today):
    t = date.fromisoformat(today)
    changed = 0
    for r in listings:
        h = hist.get(r.get("u"))
        if not h: continue
        r["first_seen"] = h["first_seen"]
        ours = (t - date.fromisoformat(h["first_seen"])).days
        dom = max(ours, int(r.get("dom_src") or 0))
        r["days_on_market"] = dom
        e = h["history"]
        drops = []
        for a, b in zip(e, e[1:]):
            pct = native_drop(a, b)
            if pct: drops.append({"date": b["date"], "from": a.get("usd"), "to": b.get("usd"), "pct": pct})
        r["price_drops"] = drops
        r["total_drop_pct"] = (native_drop(e[0], e[-1]) or 0) if drops else 0
        # distress: take off the points this script added last time, then add today's
        bd = list(r.get("distress_breakdown") or [])
        base = (r.get("distress") or 0) - sum(p for lbl, p in bd if str(lbl).startswith(OURS))
        bd = [x for x in bd if not str(x[0]).startswith(OURS)]
        add = []
        if dom >= 365: add.append(["on-market ≥365d", 30])
        elif dom >= 180: add.append(["on-market ≥180d", 18])
        elif dom >= 90: add.append(["on-market ≥90d", 8])
        tdp = r["total_drop_pct"]
        if tdp >= 20: add.append([f"price dropped {tdp}%", 30])
        elif tdp >= 10: add.append([f"price dropped {tdp}%", 18])
        elif tdp >= 5: add.append([f"price dropped {tdp}%", 8])
        new = min(100, max(0, base) + sum(p for _, p in add))
        if new != (r.get("distress") or 0):
            r["distress"] = new; changed += 1
        if bd or add: r["distress_breakdown"] = bd + add
        else: r.pop("distress_breakdown", None)
    return changed

def main():
    args = sys.argv[1:]
    today = args[args.index("--date") + 1] if "--date" in args else date.today().isoformat()
    path = args[args.index("--listings") + 1] if "--listings" in args else LIST
    listings = json.load(open(path))
    hist = load_json(HIST, {})
    n, c = update(hist, listings, today)
    os.makedirs(os.path.dirname(HIST), exist_ok=True)
    json.dump(hist, open(HIST, "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"history {today}: {len(hist)} URLs tracked, +{n} new, {c} price changes", file=sys.stderr)
    if path == LIST:
        ch = enrich(hist, listings, today)
        json.dump(listings, open(LIST, "w"), ensure_ascii=False, separators=(",", ":"))
        print(f"enriched {len(listings)} listings; distress changed on {ch}", file=sys.stderr)

if __name__ == "__main__":
    main()
