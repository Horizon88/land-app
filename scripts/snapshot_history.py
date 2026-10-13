"""Snapshot pipeline: track first_seen date + price history per listing URL.

Runs after all scrapers/merges finish. Reads docs/listings.json + data/history.json,
updates history for every URL in current listings:
  - if URL is new -> record today as first_seen
  - if price changed vs the latest history entry -> append (date, usd, lp, cur)
  - if URL disappeared -> mark last_seen (do NOT delete — it may be sold or delisted)

Then enriches listings.json with derived fields:
  - first_seen  (ISO date)
  - days_on_market
  - price_drops: list of (date, from_usd, to_usd, pct)
  - total_drop_pct (biggest cumulative drop from initial listing)

Distress signal gets updates:
  - on_market >= 90d  -> +8 (stale-listing signal)
  - on_market >= 180d -> +18
  - on_market >= 365d -> +30
  - price_drop >= 5%  -> +8
  - price_drop >= 10% -> +18
  - price_drop >= 20% -> +30

These stack with any existing distress signal (forced-sale, keywords, etc)
but max out at 100.
"""
import json, os, sys
from datetime import datetime, date

REPO = "/home/user/land-app"
LIST = f"{REPO}/docs/listings.json"
HIST = f"{REPO}/data/history.json"

def load_json(p, default):
    if not os.path.exists(p): return default
    try: return json.load(open(p))
    except: return default

def save_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(obj, open(p, "w"), ensure_ascii=False)

today = date.today().isoformat()

listings = json.load(open(LIST))
hist = load_json(HIST, {})

# Update history
new_urls = 0
price_changes = 0
current_urls = set()
for r in listings:
    u = r.get("u")
    if not u: continue
    current_urls.add(u)
    usd = r.get("usd")
    lp = r.get("lp") or str(usd or "")
    cur = r.get("cur","")
    h = hist.get(u)
    if not h:
        hist[u] = {
            "first_seen": today,
            "last_seen": today,
            "history": [{"date": today, "usd": usd, "lp": lp, "cur": cur}],
        }
        new_urls += 1
    else:
        h["last_seen"] = today
        last = h["history"][-1] if h["history"] else None
        if not last or last.get("usd") != usd:
            h["history"].append({"date": today, "usd": usd, "lp": lp, "cur": cur})
            price_changes += 1

# Mark URLs that vanished (delisted or sold)
for u, h in hist.items():
    if u not in current_urls and not h.get("delisted"):
        h["delisted"] = today

save_json(HIST, hist)
print(f"history: {len(hist)} URLs tracked, +{new_urls} new, {price_changes} price changes today", file=sys.stderr)

# Enrich listings
def days_since(iso_str):
    d = date.fromisoformat(iso_str)
    return (date.today() - d).days

def size_bonus_from_tiers(ac):
    """Bump the distress index for stale/dropped listings."""
    return 0

n_enriched = 0
n_distress_bumped = 0
for r in listings:
    u = r.get("u")
    if not u or u not in hist: continue
    h = hist[u]
    r["first_seen"] = h["first_seen"]
    dom = days_since(h["first_seen"])
    r["days_on_market"] = dom
    # Price drops
    entries = h["history"]
    drops = []
    if len(entries) > 1:
        for a, b in zip(entries, entries[1:]):
            if a.get("usd") and b.get("usd") and b["usd"] < a["usd"]:
                pct = round((a["usd"] - b["usd"]) / a["usd"] * 100, 1)
                drops.append({"date": b["date"], "from": a["usd"], "to": b["usd"], "pct": pct})
    r["price_drops"] = drops
    total_drop_pct = 0
    if drops:
        initial = entries[0].get("usd")
        current = entries[-1].get("usd")
        if initial and current and current < initial:
            total_drop_pct = round((initial - current) / initial * 100, 1)
    r["total_drop_pct"] = total_drop_pct

    # Update distress
    dist = r.get("distress", 0) or 0
    breakdown = list(r.get("distress_breakdown", []) or [])
    if dom >= 365:
        dist += 30; breakdown.append(["on-market ≥365d", 30])
    elif dom >= 180:
        dist += 18; breakdown.append(["on-market ≥180d", 18])
    elif dom >= 90:
        dist += 8; breakdown.append(["on-market ≥90d", 8])
    if total_drop_pct >= 20:
        dist += 30; breakdown.append([f"price dropped {total_drop_pct}%", 30])
    elif total_drop_pct >= 10:
        dist += 18; breakdown.append([f"price dropped {total_drop_pct}%", 18])
    elif total_drop_pct >= 5:
        dist += 8; breakdown.append([f"price dropped {total_drop_pct}%", 8])
    if dist != (r.get("distress") or 0):
        r["distress"] = min(100, dist)
        r["distress_breakdown"] = breakdown
        n_distress_bumped += 1
    n_enriched += 1

save_json(LIST, listings)
print(f"enriched {n_enriched} listings; distress bumped on {n_distress_bumped}", file=sys.stderr)
# Report on delisted (a proxy for sold — future data point)
delisted_today = sum(1 for h in hist.values() if h.get("delisted") == today)
print(f"delisted today: {delisted_today}", file=sys.stderr)
