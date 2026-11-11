"""Feed for Snowbunker Recon (Horizon88/snowrecon-public): one compact file with
the listings worth looking at on the recon map plus each country's tax notes.

Listings included: anything matching one of your hunts (digest.py's HUNTS), plus
new this week, price-cut in the last 30 days, motivated sellers, and your own
picks (saved_plots.json). Skipped/archived listings and deal-killers are left out.

Writes docs/recon_feed.json:
  {built, app, listings: [{u, c(code), la, lo, p(usd), ac, t(type), n(name), cf, v(view),
                           f: flags 'n' new / 'c' cut / 'm' motivated / 'p' pick, h: hunt keys}],
   tax: {country: {resident_days, home_rule, residency, income_top, income_abroad, income_note,
                   purchase_pct, annual_pct, property_note}}}

Usage: python3 scripts/recon_feed.py
"""
import json, os, sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from digest import HUNTS, skipped_urls

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "docs", "recon_feed.json")
APP = "https://raw.githack.com/Horizon88/land-app/main/docs/index.html"

def compact(r, flags, hunts):
    return {"u": r["u"], "c": r.get("code", ""), "la": round(r["lat"], 5), "lo": round(r["lon"], 5), "p": r.get("usd"),
            "ac": r.get("ac"), "t": r.get("tp", "land"), "n": (r.get("name") or r.get("a") or "")[:70], "cf": r.get("cf"),
            "v": r.get("view_score"), "ap": 1 if r.get("loc_approx") else 0, "f": flags, "h": hunts,
            "dom": r.get("days_on_market"), "drop": r.get("total_drop_pct") or None}

def main():
    d = json.load(open(os.path.join(ROOT, "docs", "listings.json")))
    picks = json.load(open(os.path.join(ROOT, "docs", "saved_plots.json")))
    skip = skipped_urls()
    latest = max((r.get("first_seen") or "" for r in d), default="")
    new_since = (date.fromisoformat(latest) - timedelta(days=7)).isoformat() if latest else "9999"
    cut_since = (date.fromisoformat(latest) - timedelta(days=30)).isoformat() if latest else "9999"
    out = []
    for r in d + [dict(p, user_added=True) for p in picks]:
        if r.get("lat") is None or r.get("u") in skip or r.get("deal"): continue
        flags = ""
        if (r.get("first_seen") or "") > new_since: flags += "n"
        if r.get("price_drops") and r["price_drops"][-1]["date"] > cut_since: flags += "c"
        if r.get("tp") != "apartment" and ((r.get("total_drop_pct") or 0) >= 5 or (r.get("days_on_market") or 0) >= 180): flags += "m"
        if r.get("user_added"): flags += "p"
        hunts = [k for k, _, match, _ in HUNTS if match(r)]
        if hunts or set(flags) & set("ncp"): out.append(compact(r, flags, hunts))   # motivated alone is too broad
    seen, rows = set(), []
    for r in out:
        if r["u"] in seen: continue
        seen.add(r["u"]); rows.append(r)
    tax = {}
    for cf, c in json.load(open(os.path.join(ROOT, "docs", "countries.json")))["countries"].items():
        res, inc, t = c.get("residency") or {}, c.get("income_tax") or {}, c.get("tax") or {}
        tax[cf] = {"resident_days": res.get("days"), "home_rule": res.get("home"), "residency": res.get("note"),
                   "income_top": inc.get("top"), "income_abroad": inc.get("abroad"), "income_note": inc.get("note"),
                   "purchase_pct": t.get("purchase"), "annual_pct": t.get("annual"), "property_note": t.get("note")}
    feed = {"built": latest, "app": APP, "hunts": {k: label for k, label, _, _ in HUNTS}, "listings": rows, "tax": tax}
    json.dump(feed, open(OUT, "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"recon feed: {len(rows)} listings, {len(tax)} countries -> {OUT} ({os.path.getsize(OUT) // 1024} KB)", file=sys.stderr)

if __name__ == "__main__":
    main()
