"""Enrich /tmp/olx_ro.json + /tmp/olx_pl.json with image URLs from card pages,
then re-merge listings.json so popovers + table thumbnails render properly."""
import json, re, subprocess, urllib.parse, sys

RELAY = "https://landrelay.flag-theory.workers.dev"

def via_relay(url, timeout=35):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

IMG_PAT = re.compile(r'<img[^>]*?src="(https://[^"]*olxcdn\.com[^"]+)"')

def harvest_imgs(list_url):
    """Return dict id → img URL."""
    body = via_relay(list_url)
    if not body or len(body) < 30000: return {}
    out = {}
    for c in re.split(r'<div[^>]*data-cy="l-card"', body)[1:]:
        m_id = re.search(r'id="(\d+)"', c[:200])
        m_img = IMG_PAT.search(c[:4000])
        if m_id and m_img:
            url = m_img.group(1).replace(";s=216x152", ";s=510x383").replace(";s=200x150", ";s=510x383")
            out[m_id.group(1)] = url
    return out

CONFIGS = [
    ("/tmp/olx_ro.json", "https://www.olx.ro/imobiliare/terenuri/{slug}/",
     ["brasov","prahova","suceava","hunedoara","harghita","maramures","alba","sibiu","bihor","cluj"],
     "judet"),
    ("/tmp/olx_pl.json", "https://www.olx.pl/nieruchomosci/dzialki/{slug}/",
     ["malopolskie","slaskie","podkarpackie","dolnoslaskie"],
     "woj"),
]

import time
for path, tmpl, slugs, key in CONFIGS:
    data = json.load(open(path))
    img_map = {}
    for slug in slugs:
        for page in (1, 2, 3):
            url = (tmpl.format(slug=slug) + f"?page={page}") if page > 1 else tmpl.format(slug=slug)
            new = harvest_imgs(url)
            img_map.update(new)
            print(f"  {slug} p{page}: +{len(new)} img URLs (total {len(img_map)})", file=sys.stderr)
            time.sleep(0.3)
    n = 0
    for r in data:
        if r["id"] in img_map:
            r["img"] = img_map[r["id"]]
            n += 1
    json.dump(data, open(path, "w"), ensure_ascii=False)
    print(f"  {path}: tagged {n}/{len(data)} with imgs", file=sys.stderr)
