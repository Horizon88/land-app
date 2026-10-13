"""Nominee-structure scan — Thai land listings sold by foreigners via
Thai-company vehicles.

Foreigners cannot own Thai land (Land Code s.86/96). The common workaround —
a Thai limited company holding the chanote with the foreigner controlling
49% + nominee Thai shareholders — is explicitly illegal (s.96 bis; Foreign
Business Act nominee provisions). When such an owner needs to exit, they
advertise the tell: "sold with company", "share transfer", "company name
transfer". These sellers cannot hold out — the structure is a wasting,
legally-exposed asset — which is negotiating leverage for a buyer who
insists on a clean Land Office transfer out of the company.

Scans the description block of every FazWaz Thailand listing we hold and
scores two things:
  nominee  — evidence the land is company/nominee-held by a foreigner
  exit     — evidence the seller is a foreigner who needs out

Emits /tmp/nominee_scan.json for nominee_merge.py.
"""
import json, re, subprocess, sys, time, urllib.parse, os

RELAY = "https://landrelay.flag-theory.workers.dev"

# (pattern, tag, weight) — scanned against the DESCRIPTION BLOCK only
# (whole-page scans false-positive on agency boilerplate like "FazWaz Co., Ltd")
NOMINEE_PATS = [
    # negation-guarded: "no nominee shareholders" is a denial, not an admission
    (r'(?<!no )(?<!not )(?<!without )(?<!free of )\bnominee\b', 'nominee-explicit', 35),
    (r'sold?\s+with\s+(?:the\s+)?(?:thai\s+)?company', 'sold-with-company', 30),
    (r'sale\s+with\s+(?:the\s+)?company', 'sold-with-company', 30),
    (r'(?:company|share)s?\s+transfer', 'share-transfer', 30),
    (r'transfer\s+(?:of\s+)?(?:the\s+)?(?:company|share)s?', 'share-transfer', 30),
    (r'(?:owned|held)\s+(?:by|in|through|via)\s+(?:a\s+)?(?:thai\s+)?(?:limited\s+)?company', 'company-held', 25),
    (r'freehold\s+(?:through|via|with)\s+(?:a\s+)?(?:thai\s+)?company', 'company-freehold', 30),
    (r'chanote.{0,40}company\s+name|title.{0,40}in\s+(?:the\s+)?company', 'chanote-in-company', 25),
    (r'company\s+(?:is\s+)?includ\w+|(?:includes?|comes?\s+with)\s+(?:a\s+)?(?:thai\s+)?company', 'company-included', 30),
]

# FazWaz appends the same ownership-options boilerplate to every land page —
# strip it so the tooltip text can't masquerade as seller language.
BOILERPLATE = [
    r'foreign nationals cannot own land in thailand[^.]*\.',
    r'the options for a foreigner to make use of the land[^.]*\.',
    r'thai ownership,?\s*(?:company,?\s*)?(?:leasehold)?\s*land\s*title',
]

EXIT_PATS = [
    (r'owner\s+(?:is\s+)?(?:leaving|moving|relocat\w+|returning|going)', 'owner-leaving', 20),
    (r'leaving\s+thailand|moving\s+(?:back\s+)?(?:to|abroad|overseas)', 'leaving-thailand', 20),
    (r'return\w*\s+to\s+(?:europe|the\s+uk|england|germany|australia|america|home)', 'returning-home', 20),
    (r'owner\s+(?:lives?\s+)?(?:abroad|overseas)|absentee\s+owner', 'owner-abroad', 15),
    (r'\bexpat\b|foreign\s+owner|\bfarang\b', 'foreign-owner', 12),
    (r'\burgent\w*\b|must\s+sell|quick\s+sale|fast\s+sale', 'urgent', 15),
    (r'sacrifice|below\s+(?:cost|market|value)|priced?\s+to\s+sell', 'sacrifice', 15),
    (r'price\s+(?:drop|reduc\w+|cut)|reduced\s+(?:price|from)', 'price-drop', 12),
    (r'\bdivorce\b|health\s+reasons?|retire\w+\s+sale', 'life-event', 10),
    (r'no\s+longer\s+(?:need|use|visit)|rarely\s+used', 'unused', 8),
]

def via_relay(url, timeout=35):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

def description_block(body):
    """Pull the listing's own description text, not the page chrome."""
    m = re.search(r'class="unit-view-description[^"]*"[^>]*>(.*?)</(?:section|article)>', body, re.S)
    if not m:
        m = re.search(r'class="unit-view-description[^"]*"[^>]*>(.{0,8000})', body, re.S)
    if not m:
        # og:description fallback (shorter but always present)
        m = re.search(r'property="og:description"\s+content="([^"]+)"', body)
    if not m:
        return ""
    txt = re.sub(r'<[^>]+>', ' ', m.group(1))
    return re.sub(r'\s+', ' ', txt).strip()

def ownership_field(body):
    """FazWaz structured 'Land Ownership' value, e.g. 'Thai Ownership' /
    'Thai Ownership, Company' / 'Company'."""
    m = re.search(r'Land Ownership.*?basic-information-info\s*">([^<]+)<', body, re.S)
    return m.group(1).strip() if m else ""

def info_fields(body):
    """All basic-information topic/value pairs: Date Listed, Updated,
    Land Title Deed, View(s), …"""
    pairs = re.findall(r'basic-information-topic\D{0,200}?>([A-Za-z][^<]{2,40})<.{0,600}?'
                       r'basic-information-info\s*"?>([^<]{1,60})<', body, re.S)
    return {t.strip().rstrip(':'): v.strip() for t, v in pairs}

def days_on_market(date_listed):
    """'Nov 28, 2022' → days since."""
    from datetime import datetime
    try:
        dt = datetime.strptime(date_listed, "%b %d, %Y")
        return max(0, (datetime.now() - dt).days)
    except Exception:
        return None

def scan(desc):
    dl = desc.lower()
    for pat in BOILERPLATE:
        dl = re.sub(pat, ' ', dl)
    nominee, exit_, seen = [], [], set()
    n_score = e_score = 0
    for pat, tag, w in NOMINEE_PATS:
        if tag not in seen and re.search(pat, dl):
            seen.add(tag); nominee.append(tag); n_score += w
    for pat, tag, w in EXIT_PATS:
        if tag not in seen and re.search(pat, dl):
            seen.add(tag); exit_.append(tag); e_score += w
    return nominee, min(n_score, 70), exit_, min(e_score, 50)

if __name__ == "__main__":
    import sys as _s
    listings = json.load(open('/home/user/land-app/docs/listings.json'))
    targets = [r for r in listings if r.get('cf') == 'Thailand'
               and 'fazwaz.com' in (r.get('u') or '')]
    print(f"{len(targets)} FazWaz Thailand listings to scan", file=sys.stderr)

    out_path = "/tmp/nominee_scan.json"
    out = {}
    if os.path.exists(out_path):
        out = json.load(open(out_path))
        print(f"resuming with {len(out)} cached", file=sys.stderr)

    for i, r in enumerate(targets):
        u = r['u']
        if u in out:
            continue
        body = via_relay(u)
        if not body or len(body) < 40000:
            out[u] = {"ok": False}
            time.sleep(0.2)
            continue
        desc = description_block(body)
        nominee, n_score, exit_, e_score = scan(desc)
        own = ownership_field(body)
        if own:
            opts = {o.strip().lower() for o in own.split(',')}
            if opts == {'company'}:
                # share transfer is the ONLY route offered — land is company-held freehold
                nominee.insert(0, 'company-only-transfer'); n_score += 45
            elif 'company' in opts and 'leasehold' in opts:
                # company OR lease both offered — share-transfer isn't the only exit
                nominee.append('company-or-lease-transfer'); n_score += 20
            elif 'company' in opts:
                nominee.append('offers-company-transfer'); n_score += 20
        n_score = min(n_score, 90)
        # current asking price from title (drop detection)
        m = re.search(r'for\s*\$([\d,]+)\s*\|', body)
        price_now = int(m.group(1).replace(",", "")) if m else None
        info = info_fields(body)
        dom = days_on_market(info.get("Date Listed", ""))
        rec = {"ok": True, "n": n_score, "e": e_score, "own": own,
               "hits": nominee + exit_, "price_now": price_now,
               "deed": info.get("Land Title Deed", ""),
               "listed": info.get("Date Listed", ""),
               "updated": info.get("Updated", ""),
               "views": info.get("View(s)", ""),
               "dom": dom}
        if n_score >= 20:
            rec["excerpt"] = desc[:400]
        out[u] = rec
        if (i + 1) % 25 == 0:
            json.dump(out, open(out_path, "w"))
            found = sum(1 for v in out.values() if v.get("n", 0) >= 20)
            print(f"  {i+1}/{len(targets)} scanned · {found} nominee-flagged", file=sys.stderr)
        time.sleep(0.25)

    json.dump(out, open(out_path, "w"))
    found = sum(1 for v in out.values() if v.get("n", 0) >= 20)
    lever = sum(1 for v in out.values() if v.get("n", 0) >= 20 and v.get("e", 0) >= 15)
    print(f"DONE {len(out)} scanned · {found} nominee-flagged · {lever} with exit pressure", file=sys.stderr)
