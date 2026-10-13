"""Parcl Labs Motivated Seller Index (MSI) — per state + hottest metros.

Fetches each of 50 US states via the map's `?level=county&state=XX` URL
through Cloudflare Browser Rendering (the site is CSR — direct fetch
returns only the SPA shell). Parses the state's own MSI + top / bottom
counties + top metros embedded in the JSON-LD BreadcrumbList.

Writes docs/parcl_msi.json with the shape:

  {
    "as_of": "2026-08-08",
    "national": 5.39,
    "state_msi": {"CA": 5.20, "CO": 6.07, ...},
    "metro_msi": {"Sherman, TX": 7.47, "Austin, TX": 7.29, ...},
    "county_msi": {"Los Angeles County, CA": 4.10, ...}
  }

Higher MSI = more motivated sellers = more distressed sales = better
hunting for buyers.
"""
import json, re, subprocess, sys, time, urllib.parse
from datetime import date

RELAY = "https://landrelay.flag-theory.workers.dev"

STATES = ['AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA','KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY']

def render(url, timeout=60):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}&render=1&wait=5000"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+10)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

def parse_msi(body):
    """Return {name → msi} for whatever's in the page's JSON-LD."""
    out = {}
    for m in re.finditer(r'"name":"([^"]+?)\s*-\s*MSI\s+([\d.]+)"', body):
        name = m.group(1).strip()
        try: out[name] = float(m.group(2))
        except: pass
    return out

def find_state_msi(body):
    """Extract the state's own MSI (usually in the title / description)."""
    m = re.search(r'\((?:MSI|Motivated Seller Index)\s+([\d.]+)\)', body)
    if m: return float(m.group(1))
    m = re.search(r'US MSI\s+([\d.]+)', body)
    if m: return float(m.group(1))
    return None

if __name__ == "__main__":
    out = {
        "as_of": date.today().isoformat(),
        "source": "parcllabs.com/research/motivated-sellers/map",
        "national": None,
        "state_msi": {},
        "metro_msi": {},
        "county_msi": {},
    }

    # National first
    body = render('https://www.parcllabs.com/research/motivated-sellers/map')
    out["national"] = find_state_msi(body)
    for k,v in parse_msi(body).items():
        if ',' in k or ' - ' in k:
            out["metro_msi"][k] = v
        else:
            # Full state name from national page
            out["state_msi"][k] = v
    print(f"national {out['national']} · from national page: {len(out['state_msi'])} states, {len(out['metro_msi'])} metros", file=sys.stderr)

    # Then iterate each state to pick up its own MSI + top counties/metros
    for i, st in enumerate(STATES):
        url = f'https://www.parcllabs.com/research/motivated-sellers/map?level=county&state={st}'
        body = render(url, timeout=45)
        if not body or len(body) < 20000:
            print(f"  [{i+1}/50] {st}: no data", file=sys.stderr)
            time.sleep(2); continue
        state_msi = find_state_msi(body)
        if state_msi and 1.0 < state_msi < 15.0:
            out["state_msi"][st] = state_msi
        for k,v in parse_msi(body).items():
            if 'County' in k or 'Parish' in k or 'Borough' in k:
                out["county_msi"][k] = v
            elif ',' in k:
                out["metro_msi"][k] = v
        print(f"  [{i+1}/50] {st}: MSI {state_msi} · counties so far {len(out['county_msi'])} · metros {len(out['metro_msi'])}", file=sys.stderr)
        # Persist incrementally
        json.dump(out, open("/home/user/land-app/docs/parcl_msi.json","w"), indent=2)
        time.sleep(1.5)   # avoid rate-limit on CF Browser Rendering (10 min/day free tier)

    print(f"\nFinal: {len(out['state_msi'])} states, {len(out['metro_msi'])} metros, {len(out['county_msi'])} counties", file=sys.stderr)
