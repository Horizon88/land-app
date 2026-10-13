"""Open a GitHub issue for each new high-rated listing (>=90).

Run after scan.py. Reads data/new_high.json. Uses GITHUB_TOKEN + GITHUB_REPOSITORY
from the Actions environment.
"""
from __future__ import annotations
import json, os, pathlib, sys, urllib.request, urllib.error

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"

def gh_post(repo: str, token: str, title: str, body: str, labels: list[str]) -> dict:
    url = f"https://api.github.com/repos/{repo}/issues"
    data = json.dumps({"title": title, "body": body, "labels": labels}).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "claude-land-scanner",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print("GITHUB_TOKEN / GITHUB_REPOSITORY missing — running locally?", file=sys.stderr)
        return 0
    nh_path = DATA / "new_high.json"
    if not nh_path.exists():
        print("no new_high.json — nothing to do")
        return 0
    rows = json.loads(nh_path.read_text())
    if not rows:
        print("no new high-rated listings this run")
        return 0
    for r in rows:
        title = f"[DD] [{r['country']}] {r['rating']:.0f} — {r.get('region','')} {r.get('area','')} — ${r.get('price_usd',0):,} for {r.get('acres','?')} ac"
        body = (
            f"**Rating: {r['rating']} — do further due diligence**\n"
            f"Breakdown: {r.get('rating_breakdown','')}\n\n"
            f"- Country: {r['country']}\n"
            f"- Region/area: {r.get('region','')} / {r.get('area','')}\n"
            f"- Size: {r.get('acres','?')} acres ({r.get('m2','?')} m²)\n"
            f"- Price: {r.get('price_local','?')} {r.get('currency','?')} "
            f"= US${r.get('price_usd','?'):,}\n"
            f"- USD/m²: {r.get('usd_per_m2','?')} | USD/acre: ${r.get('usd_per_acre','?'):,}\n"
            f"- View: {r.get('view','?')}\n"
            f"- Title: {r.get('title','?')}\n"
            f"- Source: {r.get('source','?')}\n\n"
            f"**Listing:** {r['listing_link']}\n"
        )
        try:
            issue = gh_post(repo, token, title, body, ["land-alert", "due-diligence", f"rating-{int(r['rating'])}"])
            print(f"opened issue #{issue.get('number')} for rating {r['rating']}")
        except urllib.error.HTTPError as e:
            print(f"HTTPError opening issue: {e.code} {e.reason}", file=sys.stderr)
        except Exception as e:
            print(f"error opening issue: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
