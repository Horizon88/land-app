"""General dead-link pruner (all sources).

Listings expire and 404 but scrapers only ever ADD rows, so dead links
accumulate. This re-checks detail URLs and removes only DEFINITIVELY dead
ones. Config-driven per domain; supersedes suumo_deadlink_check.py.

Dead signal (universal):  HTTP 404 / 410
  plus per-site text fallback (delisted phrase present AND alive-marker
  absent). A network failure / timeout / captcha-interstitial → 'unknown',
  which NEVER prunes (fail-safe: keep the row).

Fetch method per domain: 'direct' curl (SUUMO) or via the Cloudflare relay
(Thai portals — the relay forwards the upstream status code).

Never prunes user-added rows (saved_plots / manual / DOL parcels).

Cron-friendly: checks the CAP least-recently-checked rows per run, tracking
last-check dates in /tmp/deadlink_checked.json, so runs rotate through all.

Usage:  python3 scripts/deadlink_check.py [CAP]   (default 1200)
"""
import json, subprocess, sys, time, urllib.parse
from datetime import date

PATH = "/home/user/land-app/docs/listings.json"
CACHE = "/tmp/deadlink_checked.json"
RELAY = "https://landrelay.flag-theory.workers.dev"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CAP = int(sys.argv[1]) if len(sys.argv) > 1 else 1200

# domain → how to fetch + how to read the result
DOMAINS = {
    "suumo.jp":              {"via": "direct", "dead": ["掲載が終了"], "alive": ["販売価格", "土地面積"]},
    "fazwaz.com":            {"via": "relay",  "dead": ["no longer available", "page not found"], "alive": ["property-sales", "rai", "sqm", "Land"]},
    "dotproperty.co.th":     {"via": "relay",  "dead": ["no longer available", "not found"], "alive": ["offers", "price", "rai"]},
    "thailand-property.com": {"via": "relay",  "dead": ["no longer available", "not found"], "alive": ["Land area", "price", "rai"]},
    "propertyhub.in.th":     {"via": "relay",  "dead": ["ไม่พบ", "ถูกลบ", "not found"], "alive": ["ราคา", "ตารางวา", "ไร่"]},
}

def domain_of(url):
    for dom in DOMAINS:
        if dom in (url or ""):
            return dom
    return None

def fetch(url, via, timeout=25):
    if via == "relay":
        target = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    else:
        target = url
    cmd = ["curl", "-skL", "-m", str(timeout), "-A", UA,
           "-H", "Accept-Language: ja,th,en;q=0.8", "-H", "Referer: https://google.com/",
           "-w", "\n@@HTTP%{http_code}@@", target]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 6)
    except Exception:
        return None, ""
    body = r.stdout or ""
    code = ""
    if "@@HTTP" in body:
        code = body.rsplit("@@HTTP", 1)[-1].strip("@")
        body = body.rsplit("\n@@HTTP", 1)[0]
    return code, body

def status(url, cfg):
    code, body = fetch(url, cfg["via"])
    if code in ("404", "410"):
        return "dead"
    if code is None or not body or len(body) < 2000:
        return "unknown"
    has_alive = any(s in body for s in cfg.get("alive", []))
    has_dead = any(s in body for s in cfg.get("dead", []))
    if has_dead and not has_alive:
        return "dead"
    if has_alive:
        return "alive"
    return "unknown"

def main():
    d = json.load(open(PATH))
    try:
        checked = json.load(open(CACHE))
    except Exception:
        checked = {}

    targets = [r for r in d
               if domain_of(r.get("u")) and not r.get("user_added") and r.get("source") != "dol"]
    targets.sort(key=lambda r: checked.get(r["u"], ""))   # oldest-checked first
    batch = targets[:CAP]
    from collections import Counter
    print(f"{len(targets)} checkable rows; this run {len(batch)} "
          f"({dict(Counter(domain_of(r['u']) for r in batch))})", file=sys.stderr)

    today = date.today().isoformat()
    dead_urls = set()
    dead = alive = unknown = 0
    for i, r in enumerate(batch):
        st = status(r["u"], DOMAINS[domain_of(r["u"])])
        if st == "dead":
            dead_urls.add(r["u"]); dead += 1
        elif st == "alive":
            alive += 1
        else:
            unknown += 1
        checked[r["u"]] = today
        if (i + 1) % 100 == 0:
            json.dump(checked, open(CACHE, "w"))
            print(f"  {i+1}/{len(batch)} · dead {dead} alive {alive} unknown {unknown}", file=sys.stderr)
        time.sleep(0.3)

    json.dump(checked, open(CACHE, "w"))
    if dead_urls:
        before = len(d)
        d = [r for r in d if r.get("u") not in dead_urls]
        json.dump(d, open(PATH, "w"), separators=(",", ":"))
        print(f"PRUNED {before - len(d)} dead listings "
              f"(dead {dead}, alive {alive}, unknown {unknown}); total now {len(d)}", file=sys.stderr)
    else:
        print(f"no dead links this batch (alive {alive}, unknown {unknown})", file=sys.stderr)

if __name__ == "__main__":
    main()
