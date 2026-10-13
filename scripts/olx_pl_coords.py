"""Re-fetch coords for all OLX-PL cards using the escaped-JSON regex."""
import json, re, subprocess, sys, time, urllib.parse

RELAY = "https://landrelay.flag-theory.workers.dev"

def via_relay(url, timeout=30):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

# Match BOTH the plain "latitude":xx and escaped lat\":xx (Next.js stream)
LAT_PATS = [
    re.compile(r'"latitude"\s*:\s*"?([-\d.]+)[^"\d.]'),
    re.compile(r'\blat\\?\"?\s*:\s*\\?\"?([-\d.]+)'),
]
LNG_PATS = [
    re.compile(r'"longitude"\s*:\s*"?([-\d.]+)[^"\d.]'),
    re.compile(r'\blng\\?\"?\s*:\s*\\?\"?([-\d.]+)'),
    re.compile(r'\blon\\?\"?\s*:\s*\\?\"?([-\d.]+)'),
]

def extract_coords(body):
    lat = lng = None
    for p in LAT_PATS:
        m = p.search(body)
        if m:
            try: lat = float(m.group(1)); break
            except: pass
    for p in LNG_PATS:
        m = p.search(body)
        if m:
            try: lng = float(m.group(1)); break
            except: pass
    return lat, lng

d = json.load(open("/tmp/olx_pl.json"))
print(f"loaded {len(d)} cards", file=sys.stderr)
n_fixed = 0
for i, r in enumerate(d):
    if not r.get("url"): continue
    fb_lat = r.get("fb_lat") or 0
    # Skip if already has real coords (not fallback)
    if r.get("lat") and abs(r["lat"] - fb_lat) > 0.01:
        continue
    body = via_relay(r["url"], timeout=25)
    if not body or len(body) < 50000:
        continue
    lat, lng = extract_coords(body)
    if lat and lng:
        # Sanity: PL is roughly 49-55 N, 14-24 E
        if 48 < lat < 56 and 13 < lng < 25:
            r["lat"] = lat; r["lng"] = lng
            n_fixed += 1
    if i and i % 25 == 0:
        json.dump(d, open("/tmp/olx_pl.json", "w"), ensure_ascii=False)
        print(f"  {i}/{len(d)} done (fixed: {n_fixed})", file=sys.stderr)
    time.sleep(0.2)

json.dump(d, open("/tmp/olx_pl.json", "w"), ensure_ascii=False)
real = sum(1 for r in d if r.get("lat") and abs(r["lat"] - (r.get("fb_lat") or 0)) > 0.01)
print(f"\nfinal: {real}/{len(d)} cards with real coords (fixed {n_fixed} this run)", file=sys.stderr)
