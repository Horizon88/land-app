"""Seller-pressure score for Thai listings: who is likely to drop the price soon?

Writes onto every Thai listing (docs/listings.json and docs/saved_plots.json):
  pressure      0-100
  pressure_why  the reasons, strongest first

Signals (points):
  price cuts            total cut >=5% +10, >=10% +18, >=20% +25; two or more cuts +5
  time on market        >=6 months +6, >=1 year +12, >=2 years +18
  company-held          the listing offers company ownership / a share transfer / Thai company +15
                        (the owners most exposed to the nominee crackdown)
  urgent wording        urgent, must sell, motivated, price reduced, ขายด่วน, ลดราคา ... +12
  several agencies      the same plot (same size and price, within 1 km) listed by 2 / 3+ agencies +8 / +12
  priced under the area $/m2 under 70% of the same area's median +6
  crackdown news        nominee / DSI / land-office actions in the same area in the last 60 days
                        (data/th_pressure_news.json) +5 each, up to +15
  company filings       DBD data for the seller company (data/th_companies.json, filled by
                        scripts/th_company_lookup.py): dissolving / in liquidation +25, not operating +15,
                        foreign capital 39-49.99% with Thai majority (classic nominee split) +10,
                        losses or no revenue for 2+ years +8, accounts not filed for the last year +10
  the title deed        what Amy finds on the back of the deed (data/th_companies.json):
                        a seizure / freeze order (อายัด) +25, a bank mortgage +10
Capped at 100.

Usage: python3 scripts/th_pressure.py
"""
import json, math, os, re, statistics, sys
from collections import defaultdict
from datetime import date, timedelta

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIST = os.path.join(ROOT, "docs", "listings.json")
SAVED = os.path.join(ROOT, "docs", "saved_plots.json")
NEWS = os.path.join(ROOT, "data", "th_pressure_news.json")
COMPANIES = os.path.join(ROOT, "data", "th_companies.json")

COMPANY = re.compile(r"company (?:ownership|owned|transfer|name)|thai company|share transfer|transfer (?:of )?shares|co\.,? ?ltd|"
                     r"offers-company-transfer|limited company|บริษัท|โอนหุ้น", re.I)
URGENT = re.compile(r"urgent|must sell|motivated seller|price (?:reduced|drop|cut)|reduced price|below market|fire sale|"
                    r"quick sale|owner (?:must|needs to) sell|ขายด่วน|ด่วน|ลดราคา|ขายถูก", re.I)
AREAS = {"samui": r"samui", "phangan": r"phangan|pha ngan", "tao": r"koh tao|ko tao", "phuket": r"phuket",
         "krabi": r"krabi|ao nang|lanta", "phang nga": r"phang ?nga|khao lak", "hua hin": r"hua hin|pranburi|prachuap",
         "pattaya": r"pattaya|chonburi|jomtien", "chiang mai": r"chiang mai", "koh chang": r"koh chang|trat"}

def area_of(r):
    t = f"{r.get('rg', '')} {r.get('a', '')} {r.get('u', '')}".lower()
    for k, rx in AREAS.items():
        if re.search(rx, t): return k
    return (r.get("rg") or "").lower()

def km(a, b):
    return math.hypot((a["lon"] - b["lon"]) * 111.32 * math.cos(math.radians(a["lat"])), (a["lat"] - b["lat"]) * 110.57)

def domain(u):
    m = re.match(r"https?://(?:www\.)?([^/]+)", u or "")
    return m.group(1) if m else ""

def text_of(r):
    n = r.get("nominee") or {}
    return " ".join(str(x) for x in (r.get("name"), r.get("t"), r.get("desc"), n.get("own"), " ".join(n.get("hits") or []),
                                      n.get("excerpt"), " ".join(r.get("distress_keywords") or []) if isinstance(r.get("distress_keywords"), list) else r.get("distress_keywords")) if x)

def load(p, default):
    try: return json.load(open(p))
    except Exception: return default

def main():
    d, saved = load(LIST, []), load(SAVED, [])
    news, comp = load(NEWS, {}), load(COMPANIES, {})
    rows = [r for r in d + saved if r.get("cf") == "Thailand"]
    today = date.today()
    recent = {}
    for area, items in (news.get("areas") or {}).items():
        recent[area] = [x for x in items if x.get("date", "") >= (today - timedelta(days=60)).isoformat()]
    # area medians of $/m2 per type
    by = defaultdict(list)
    for r in rows:
        if r.get("upm"): by[(area_of(r), r.get("tp"))].append(r["upm"])
    med = {k: statistics.median(v) for k, v in by.items() if len(v) >= 8}
    # same plot on several agencies: same type, size within 3%, price within 10%, within 1 km, other domain
    pinned = [r for r in rows if r.get("lat") is not None and r.get("m2") and r.get("usd")]
    cells = defaultdict(list)
    for r in pinned: cells[(round(r["lat"], 1), round(r["lon"], 1))].append(r)
    for r in rows:
        why = []
        tdp, cuts = r.get("total_drop_pct") or 0, len(r.get("price_drops") or [])
        if tdp >= 20: why.append((25, f"price cut {tdp:g}%"))
        elif tdp >= 10: why.append((18, f"price cut {tdp:g}%"))
        elif tdp >= 5: why.append((10, f"price cut {tdp:g}%"))
        if cuts >= 2: why.append((5, f"{cuts} price cuts"))
        dom = max(r.get("days_on_market") or 0, (r.get("nominee") or {}).get("dom") or 0)
        if dom >= 730: why.append((18, f"{dom} days on the market"))
        elif dom >= 365: why.append((12, f"{dom} days on the market"))
        elif dom >= 180: why.append((6, f"{dom} days on the market"))
        t = text_of(r)
        if COMPANY.search(t): why.append((15, "company-held (offers company ownership / share transfer)"))
        if URGENT.search(t): why.append((12, "urgent-sale wording"))
        if r in pinned:
            others = {domain(o["u"]) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                      for o in cells.get((round(r["lat"], 1) + dy / 10, round(r["lon"], 1) + dx / 10), [])
                      if o is not r and o.get("tp") == r.get("tp") and abs(o["m2"] - r["m2"]) <= 0.03 * r["m2"]
                      and abs(o["usd"] - r["usd"]) <= 0.10 * r["usd"] and km(o, r) <= 1 and domain(o["u"]) != domain(r["u"])}
            if len(others) >= 2: why.append((12, f"listed by {len(others) + 1} agencies"))
            elif len(others) == 1: why.append((8, "listed by 2 agencies"))
        m = med.get((area_of(r), r.get("tp")))
        if m and r.get("upm") and r["upm"] < 0.7 * m: why.append((6, f"{r['upm'] / m:.0%} of the area's price per m²"))
        n = recent.get(area_of(r)) or []
        if n: why.append((min(15, 5 * len(n)), f"{len(n)} crackdown news item{'s' if len(n) > 1 else ''} for {area_of(r).title()} in 60 days"))
        c = comp.get(r.get("u")) or {}
        st = (c.get("status") or "").lower()
        if re.search(r"liquidat|dissol|เลิก|ชำระบัญชี|ร้าง", st): why.append((25, f"seller company {c.get('status')} (closing / struck off)"))
        elif st and not re.search(r"active|operating|ยังดำเนินกิจการ|คงอยู่|ฟื้นฟู", st): why.append((15, f"seller company status: {c.get('status')}"))
        f = c.get("foreign_pct")
        if f is not None and 39 <= f < 50: why.append((10, f"seller company {f:g}% foreign-held (classic 49/51 split)"))
        if c.get("loss_years", 0) >= 2: why.append((8, f"seller company: no profit for {c['loss_years']} years"))
        if c.get("accounts_missing"): why.append((10, "seller company hasn't filed its latest accounts"))
        if c.get("deed_seizure"): why.append((25, "seizure / freeze order on the title deed"))
        if c.get("deed_mortgage"): why.append((10, "bank mortgage on the title deed"))
        why.sort(key=lambda x: -x[0])
        r["pressure"] = min(100, sum(p for p, _ in why))
        r["pressure_why"] = [w for _, w in why]
    json.dump(d, open(LIST, "w"), separators=(",", ":"), ensure_ascii=False)
    json.dump(saved, open(SAVED, "w"), ensure_ascii=False, indent=4)
    top = sorted(rows, key=lambda r: -r["pressure"])[:12]
    print(f"Thai pressure score on {len(rows)} listings; {sum(1 for r in rows if r['pressure'] >= 30)} at 30+", file=sys.stderr)
    for r in top:
        print(f"  {r['pressure']:3} {r.get('code', '')} {area_of(r)} ${r.get('usd') or 0:,}: {'; '.join(r['pressure_why'])}", file=sys.stderr)

if __name__ == "__main__":
    main()
