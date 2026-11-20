"""Talk to the Land Command Center sheet through its Apps Script web app (scripts/command_center.gs).

Needs CC_URL (the web app URL) and CC_TOKEN (the token setup() printed) in the environment.

  python3 scripts/command_center.py tabs
  python3 scripts/command_center.py read Pipeline > pipeline.json
  python3 scripts/command_center.py upsert Pipeline rows.json [key]     (key defaults to "Lead ID")
  python3 scripts/command_center.py append "New leads" rows.json
  python3 scripts/command_center.py replace Today table.json            ({"headers": [...], "rows": [[...]]})
"""
import json, os, subprocess, sys

def call(payload):
    url, token = os.environ.get("CC_URL"), os.environ.get("CC_TOKEN")
    if not url or not token: raise SystemExit("Set CC_URL and CC_TOKEN (see scripts/command_center.gs)")
    payload = dict(payload, token=token)
    # Apps Script answers POSTs with a redirect to the result; curl -L follows it as a GET
    out = subprocess.run(["curl", "-sSL", "-m", "120", "-H", "Content-Type: application/json",
                          "--data-binary", json.dumps(payload, ensure_ascii=False), url], capture_output=True, text=True)
    try: res = json.loads(out.stdout)
    except Exception: raise SystemExit(f"Command Center did not answer with JSON: {out.stdout[:300]} {out.stderr[:200]}")
    if res.get("error"): raise SystemExit(f"Command Center error: {res['error']}")
    return res

def main(a):
    if not a: raise SystemExit(__doc__)
    act = a[0]
    if act == "tabs": print(json.dumps(call({"action": "tabs"})["tabs"], ensure_ascii=False))
    elif act == "read": print(json.dumps(call({"action": "read", "tab": a[1]})["rows"], ensure_ascii=False, default=str))
    elif act in ("upsert", "append"):
        rows = json.load(open(a[2]))
        p = {"action": act, "tab": a[1], "rows": rows}
        if act == "upsert": p["key"] = a[3] if len(a) > 3 else "Lead ID"
        print(json.dumps(call(p)))
    elif act == "replace":
        t = json.load(open(a[2]))
        print(json.dumps(call({"action": "replace", "tab": a[1], "headers": t["headers"], "rows": t["rows"]})))
    else: raise SystemExit(__doc__)

if __name__ == "__main__":
    main(sys.argv[1:])
