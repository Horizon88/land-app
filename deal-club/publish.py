"""Upload deal-club/out/picks.json to the paywall worker and mark the codes as posted.

Usage: CLUB_URL=https://land-deal-club.<you>.workers.dev CLUB_ADMIN_TOKEN=... python3 deal-club/publish.py
"""
import json, os, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
picks = json.load(open(os.path.join(ROOT, "deal-club", "out", "picks.json")))
req = urllib.request.Request(
    os.environ["CLUB_URL"].rstrip("/") + "/admin/publish", data=json.dumps(picks).encode(), method="POST",
    headers={"Authorization": "Bearer " + os.environ["CLUB_ADMIN_TOKEN"], "Content-Type": "application/json"})
print(json.load(urllib.request.urlopen(req)))

path = os.path.join(ROOT, "deal-club", "posted.json")
posted = json.load(open(path)) if os.path.exists(path) else []
posted += [p["teaser"]["code"] for p in picks if p["teaser"]["code"] not in posted]
json.dump(posted, open(path, "w"), indent=0)
print(f"{len(posted)} codes in deal-club/posted.json (commit it so the next run skips them)")
