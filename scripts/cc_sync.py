"""Daily Command Center run: keep the Land Command Center sheet and the land app in step.

Needs CC_URL and CC_TOKEN (scripts/command_center.gs). Steps:
  1. Pipeline -> data/pipeline.json -> the Leads swipe deck (scripts/leads_deck.py)
  2. Ed / Siri swipes from the family page (docs/family/state.json) -> Pipeline swipe columns
  3. New finds since the last run (hunt matches from the land app, scout / inbox / Thai picks)
     -> "New leads" tab, skipping anything already in the sheet
  4. A fresh "Today" tab: deadlines in the next 21 days, leads with no update for 10+ days,
     what's waiting at each stage, and the new leads
State: data/cc_state.json (last run date, links already sent).

Usage: python3 scripts/cc_sync.py [--dry-run]
"""
import json, os, re, subprocess, sys
from datetime import date, datetime, timedelta

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import command_center as cc
from digest import HUNTS

STATE = os.path.join(ROOT, "data", "cc_state.json")
APP = "https://raw.githack.com/Horizon88/land-app/main/docs/index.html#"
DRY = "--dry-run" in sys.argv

def load(p, d):
    try: return json.load(open(p))
    except Exception: return d

def as_date(v):
    s = str(v or "")[:10]
    try: return date.fromisoformat(s)
    except Exception: return None

def main():
    st = load(STATE, {"last": (date.today() - timedelta(days=3)).isoformat(), "sent": []})
    today = date.today()
    pipe = cc.call({"action": "read", "tab": "Pipeline"})["rows"]
    # 1. leads deck
    rows = [{"id": r.get("Lead ID"), "strategy": r.get("Strategy"), "name": r.get("Lead"), "region": r.get("Where"),
             "stage": r.get("Stage"), "lead": r.get("Our owner (who drives it)"), "next": r.get("Next action"),
             "seller": r.get("Seller / owner of record"), "ask": r.get("Asking"), "key": r.get("Why it matters"),
             "blocker": r.get("Main blocker / risk"), "grade": r.get("Evidence grade"), "link": r.get("Source link"),
             "lat": r.get("Lat"), "lon": r.get("Lon"), "updated": str(r.get("Last update") or "")} for r in pipe if r.get("Lead ID")]
    json.dump(rows, open(os.path.join(ROOT, "data", "pipeline.json"), "w"), ensure_ascii=False, default=str)
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "leads_deck.py")], check=False)
    # 2. swipes
    fam = load(os.path.join(ROOT, "docs", "family", "state.json"), {})
    votes = fam.get("votes", {})
    ids = {r["id"] for r in rows}
    sw = []
    for r in rows:
        e = (votes.get("ed") or {}).get(r["id"], {}).get("d"); s = (votes.get("partner") or {}).get(r["id"], {}).get("d")
        if e or s:
            up = {"Lead ID": r["id"]}
            if e: up["Ed swipe"] = e
            if s: up["Siri swipe"] = s
            sw.append(up)
    # 3. new leads
    d = load(os.path.join(ROOT, "docs", "listings.json"), []); picks = load(os.path.join(ROOT, "docs", "saved_plots.json"), [])
    links_in_sheet = {str(r.get("Source link") or "") for r in pipe} | {APP + i for i in ids}
    links_in_sheet |= {str(r.get("Link") or "") for r in cc.call({"action": "read", "tab": "New leads"})["rows"]}
    sent = set(st.get("sent", []))
    new = []
    for r in d:
        if (r.get("first_seen") or "") <= st["last"] or not r.get("code"): continue
        hits = [label for key, label, match, _ in HUNTS if match(r)]
        if not hits: continue
        new.append((r.get("view_score") or 0, r, "; ".join(hits)))
    new.sort(key=lambda x: -x[0])
    out = []
    for _, r, why in new[:20]:
        link = APP + r["code"]
        if link in links_in_sheet or link in sent: continue
        out.append({"Found": today.isoformat(), "By (scout / digest / inbox / person)": "daily refresh", "Lead": (r.get("name") or "")[:90],
                    "Where": f"{r.get('a') or ''}, {r.get('cf')}", "Price": f"${r['usd']:,}" if r.get("usd") else "", "Why": why, "Link": link})
    for r in picks:
        if (r.get("added") or "") <= st["last"] or not r.get("code"): continue
        link = APP + r["code"]
        if link in links_in_sheet or link in sent: continue
        src = r.get("rb", "")
        out.append({"Found": r.get("added"), "By (scout / digest / inbox / person)": "scout" if "scout" in src else "Thai distressed run" if "th-distressed" in src else "inbox / Instagram",
                    "Lead": (r.get("name") or "")[:90], "Where": f"{r.get('a') or ''}, {r.get('cf')}", "Price": f"${r['usd']:,}" if r.get("usd") else "",
                    "Why": "; ".join((r.get("perks") or [])[:2]), "Link": link})
    # 4. today
    dl = cc.call({"action": "read", "tab": "Deadlines"})["rows"]
    t = []
    for x in dl:
        dd = as_date(x.get("Date"))
        if dd and today <= dd <= today + timedelta(days=21):
            t.append(["⏰ Deadline", f"{dd.isoformat()} · {x.get('Lead')}", x.get("What") or ""])
    from collections import Counter
    for stage, n in sorted(Counter(r["stage"] or "?" for r in rows).items()):
        t.append(["📊 Pipeline", stage, f"{n} lead{'s' if n != 1 else ''}"])
    stuck = [r for r in rows if not str(r["stage"]).startswith(("1", "8", "x")) and (as_date(r["updated"]) or today) <= today - timedelta(days=10)]
    for r in stuck[:25]:
        t.append(["🐢 No update 10+ days", f"{r['id']} · {r['name']}", f"{r['lead']}: {r['next']}"])
    for x in out[:20]:
        t.append(["🆕 New lead", f"{x['Lead']} ({x['Where']})", f"{x['Price']} · {x['Why']}"])
    if sw: t.append(["💞 Swipes", f"{len(sw)} leads swiped", "copied into the Pipeline's Ed / Siri columns"])
    t.insert(0, ["Updated", datetime.now().strftime("%Y-%m-%d %H:%M UTC"), "by the daily Command Center run"])
    print(f"cc_sync: {len(rows)} pipeline rows, {len(sw)} swipe updates, {len(out)} new leads, {len(t)} Today rows", file=sys.stderr)
    if DRY: return
    if sw: cc.call({"action": "upsert", "tab": "Pipeline", "key": "Lead ID", "rows": sw})
    if out: cc.call({"action": "append", "tab": "New leads", "rows": out})
    cc.call({"action": "replace", "tab": "Today", "headers": ["What", "Item", "Detail"], "rows": t})
    st["last"] = today.isoformat(); st["sent"] = sorted(sent | {x["Link"] for x in out})[-5000:]
    json.dump(st, open(STATE, "w"), indent=1)

if __name__ == "__main__":
    main()
