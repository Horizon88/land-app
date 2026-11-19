"""Fill seller-company checks in data/th_companies.json from Thailand's DBD register via Apify.

data/th_companies.json maps a listing URL to its seller company: {"juristic_id": "13 digits"}
(or {"name": "company name"} when you only have the name). For each company not looked up in
the last 30 days this calls the Apify actor foxlabs/thailand-company-data (pay per company,
about US$0.025 each, nothing monthly) and writes back:
  name, status (as DBD writes it), foreign_pct (foreign share of capital, from the latest
  shareholder filing), loss_years (latest years in a row with a loss or no revenue),
  accounts_missing (last year's accounts not filed), registered_capital, paidup_capital,
  directors, dbd_checked (date)
scripts/th_pressure.py turns these into seller-pressure points.

The Apify token is not stored here: the cloud environment's network secret for api.apify.com
adds it to the request (or set APIFY_TOKEN when running elsewhere).

Usage: python3 scripts/th_company_lookup.py [--max N] [--dry-run]
"""
import json, os, subprocess, sys
from datetime import date, timedelta

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PATH = os.path.join(ROOT, "data", "th_companies.json")
ACTOR = "https://api.apify.com/v2/acts/foxlabs~thailand-company-data/run-sync-get-dataset-items"
PRICE = 0.025

def call(payload):
    token = os.environ.get("APIFY_TOKEN", "placeholder-the-proxy-replaces-this")
    out = subprocess.run(["curl", "-sS", "-m", "300", "-X", "POST", ACTOR, "-H", "Content-Type: application/json",
                          "-H", f"Authorization: Bearer {token}", "--data-binary", json.dumps(payload)],
                         capture_output=True, text=True)
    try: return json.loads(out.stdout)
    except Exception: raise SystemExit(f"Apify call failed: {out.stdout[:300]} {out.stderr[:300]}")

def summarise(c):
    fin = sorted(c.get("financials") or [], key=lambda f: -(f.get("fiscal_year") or 0))
    loss = 0
    for f in fin:
        if (f.get("net_profit") or 0) <= 0 or not (f.get("revenue") or f.get("total_income")): loss += 1
        else: break
    foreign = None
    if c.get("shareholders_by_nationality"):
        foreign = round(sum(s.get("share_pct") or 0 for s in c["shareholders_by_nationality"] if s.get("nationality_th") != "ไทย"), 2)
    # accounts for year Y are due by about May of Y+1
    t = date.today(); due = t.year - 1 if t.month >= 6 else t.year - 2
    filed = c.get("fiscal_years_filed") or []
    return {"juristic_id": c.get("juristic_id"), "name": c.get("name_en") or c.get("name_th"), "status": c.get("status"),
            "foreign_pct": foreign, "loss_years": loss, "accounts_missing": bool(filed) and max(filed) < due,
            "registered_capital": c.get("registered_capital"), "paidup_capital": c.get("paidup_capital"),
            "directors": c.get("directors_text"), "dbd_checked": t.isoformat()}

def main():
    args = sys.argv[1:]
    cap = int(args[args.index("--max") + 1]) if "--max" in args else 40
    data = json.load(open(PATH))
    stale = (date.today() - timedelta(days=30)).isoformat()
    todo = [(u, e) for u, e in data.items() if not u.startswith("_") and isinstance(e, dict)
            and (e.get("juristic_id") or e.get("name")) and (e.get("dbd_checked") or "") < stale][:cap]
    if not todo: print("th_company_lookup: nothing to look up", file=sys.stderr); return
    ids = sorted({e["juristic_id"] for _, e in todo if e.get("juristic_id")})
    names = sorted({e["name"] for _, e in todo if not e.get("juristic_id") and e.get("name")})
    print(f"th_company_lookup: {len(ids)} IDs + {len(names)} names, about US${PRICE * (len(ids) + len(names)):.2f}", file=sys.stderr)
    if "--dry-run" in args: return
    rows = call({"juristicIds": ids, "searchKeywords": names, "includeShareholders": True, "includeDirectors": True,
                 "financialYears": 3, "maxResults": max(1, len(ids) + len(names))})
    if isinstance(rows, dict): raise SystemExit(f"Apify error: {json.dumps(rows)[:300]}")
    by_id = {r.get("juristic_id"): r for r in rows if r.get("matched")}
    by_kw = {r.get("search_keyword"): r for r in rows if r.get("matched") and r.get("search_keyword")}
    n = 0
    for u, e in todo:
        r = by_id.get(e.get("juristic_id")) or by_kw.get(e.get("name"))
        if not r: e["dbd_note"] = "not found on DBD"; continue
        e.update(summarise(r)); n += 1
    json.dump(data, open(PATH, "w"), ensure_ascii=False, indent=1)
    print(f"th_company_lookup: updated {n} of {len(todo)}", file=sys.stderr)

if __name__ == "__main__":
    main()
