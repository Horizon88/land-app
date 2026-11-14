"""Family page sync: copy swipes, names and sent links from the ntfy.sh topic into
docs/family/state.json (the page posts them there with no login; ntfy keeps
messages ~12 h, so run this at least every few hours).

Each vote keeps the latest decision per person and plot; links are added to the
inbox with status "new" for the scout to research (it then sets status / reply /
app_url on the inbox entry). Prints the inbox entries still waiting.

Usage: python3 scripts/family_sync.py
"""
import json, os, subprocess, sys
from datetime import date

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PATH = os.path.join(ROOT, "docs", "family", "state.json")
TOPIC = "https://ntfy.sh/landapp-9a88f8c4c71c"
ROLES = ("ed", "partner")

def main():
    st = json.load(open(PATH)) if os.path.exists(PATH) else {}
    st.setdefault("votes", {r: {} for r in ROLES}); st.setdefault("names", {}); st.setdefault("inbox", [])
    for r in ROLES: st["votes"].setdefault(r, {})
    raw = subprocess.run(["curl", "-s", "-m", "30", f"{TOPIC}/json?poll=1&since=all"], capture_output=True, text=True).stdout
    have = {x["id"] for x in st["inbox"]}
    n_votes = n_links = 0
    for line in raw.splitlines():
        try:
            e = json.loads(line)
            if e.get("event") != "message": continue
            m = json.loads(e["message"])
        except Exception:
            continue
        who = m.get("who")
        if m.get("k") == "v" and who in ROLES and m.get("code"):
            cur = st["votes"][who].get(m["code"])
            if not cur or cur.get("ts", 0) <= m.get("ts", 0):
                if m.get("d") in ("keep", "skip", "maybe"): st["votes"][who][m["code"]] = {"d": m["d"], "ts": m.get("ts", 0)}
                else: st["votes"][who].pop(m["code"], None)
                n_votes += 1
        elif m.get("k") == "r" and who in ROLES and isinstance(m.get("order"), list):
            st.setdefault("ranks", {})
            cur = st["ranks"].get(who)
            if not cur or cur.get("ts", 0) <= m.get("ts", 0):
                st["ranks"][who] = {"order": [str(c)[:20] for c in m["order"][:300]], "ts": m.get("ts", 0)}
        elif m.get("k") == "n" and who in ROLES and m.get("name"):
            st["names"][who] = str(m["name"])[:40]
        elif m.get("k") == "l" and m.get("id") and m.get("url") and m["id"] not in have:
            st["inbox"].append({"id": str(m["id"])[:40], "url": str(m["url"])[:500], "note": str(m.get("note") or "")[:300],
                                "who": who if who in ROLES else "", "at": m.get("at") or "", "status": "new"})
            have.add(m["id"]); n_links += 1
    st["updated"] = date.today().isoformat()
    json.dump(st, open(PATH, "w"), ensure_ascii=False, indent=1)
    both = [c for c, v in st["votes"]["ed"].items() if v.get("d") == "keep" and st["votes"]["partner"].get(c, {}).get("d") == "keep"]
    waiting = [x for x in st["inbox"] if x.get("status") == "new"]
    print(f"family sync: {n_votes} votes, {n_links} new links; matches {len(both)}; inbox waiting {len(waiting)}", file=sys.stderr)
    for x in waiting: print(json.dumps(x, ensure_ascii=False))

if __name__ == "__main__":
    main()
