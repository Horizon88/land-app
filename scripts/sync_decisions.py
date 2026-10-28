"""Write docs/decisions.json, the permanent keep / skip / maybe list the app loads.

Sources, merged into what's already there:
  - a Plot Swipe database export (ArtifactData list with out_dir): votes/<uid>/picks/<code>.json
  - optional JSON pasted from the app's "📋 Copy archives + stars" button ({archives, stars})
Rules when several people voted on one listing: anyone's keep wins, then maybe; skip only
when everyone who voted skipped it.

Usage: python3 scripts/sync_decisions.py [export_dir] [pasted.json]
"""
import glob, json, os, sys, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PATH = os.path.join(ROOT, "docs", "decisions.json")
RANK = {"keep": 2, "maybe": 1, "skip": 0}

def main(export_dir=None, pasted=None):
    cur = json.load(open(PATH)) if os.path.exists(PATH) else {}
    out = {k: dict(cur.get(k, {})) for k in ("keep", "maybe", "skip")}
    votes = {}
    if export_dir:
        for f in glob.glob(os.path.join(export_dir, "votes", "*", "picks", "*.json")):
            b = json.load(open(f)); b = b.get("data", b)
            u, d = b.get("u"), b.get("d")
            if not u or d not in RANK: continue
            uid = f.split(os.sep)[-3]
            votes.setdefault(u, {"code": b.get("code", ""), "by": {}})["by"][uid] = (d, b.get("ts", 0))
    for u, v in votes.items():
        ds = [d for d, _ in v["by"].values()]
        best = max(ds, key=RANK.get)
        if best == "skip" and any(d != "skip" for d in ds): best = "maybe"
        for k in out: out[k].pop(u, None)
        out[best][u] = {"code": v["code"], "ts": max(t for _, t in v["by"].values()), "voters": len(v["by"]),
                        "tags": ["swipe-" + best]}
    if pasted:
        p = json.load(open(pasted))
        for u, a in (p.get("stars") or {}).items():
            for k in ("maybe", "skip"): out[k].pop(u, None)
            out["keep"][u] = {"code": a.get("code", ""), "ts": a.get("ts", 0), "tags": a.get("tags") or ["promoted"], "reason": a.get("reason", "")}
    doc = {"schema": "decisions_v1", "updated": time.strftime("%Y-%m-%d"),
           "note": "Permanent keep/skip/maybe decisions from Plot Swipe and promoted stars. The app loads this on every visit: keeps are stars, skips are archived.",
           **out}
    json.dump(doc, open(PATH, "w"), ensure_ascii=False, indent=1)
    print(f"decisions.json: {len(out['keep'])} keep · {len(out['maybe'])} maybe · {len(out['skip'])} skip", file=sys.stderr)

if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a and a[0] != "-" else None, a[1] if len(a) > 1 else None)
