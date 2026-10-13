"""LandQuest — BC + Alberta rural/recreational/mountain land specialist.

Clean server-rendered cards: title, region, price, acreage. Detail pages
embed real lat/lng. No bot wall (plain curl works).

Emits /tmp/landquest.json for landquest_merge.py.
"""
import json, re, subprocess, sys, time, os

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

INDEXES = [
    ("BC", "listings-british-columbia", 30),
    ("AB", "listings-alberta", 8),
]

def curl(url, timeout=25):
    try:
        return subprocess.run(["curl", "-sL", "-m", str(timeout), "-A", UA, url],
                              capture_output=True, text=True, timeout=timeout + 5).stdout
    except Exception:
        return ""

CARD_RE = re.compile(
    r'<h3 class="listing-card__header"><a class="listing-card__header" href="(/listings/[a-z0-9-]+)">([^<]+)</a></h3>'
    r'.*?listing-card__region"\s*>\s*([^<]+?)\s*</label>'
    r'.*?Listing No\.\s*(\d+)'
    r'.*?listing-card__price">\$([0-9,]+)</span>'
    r'\s*<small class="listing-card__size">([^<]*)</small>',
    re.S)

def parse_size_acres(s):
    s = s.strip().lower().replace(",", "")
    m = re.search(r'([0-9.]+)\s*acres?', s)
    if m: return float(m.group(1))
    m = re.search(r'([0-9.]+)\s*(?:sq\.?\s*ft|ft2)', s)
    if m: return float(m.group(1)) / 43560
    m = re.search(r'([0-9.]+)\s*hectares?', s)
    if m: return float(m.group(1)) * 2.47105
    return None

def detail_coords(url_path):
    h = curl(f"https://www.landquest.com{url_path}")
    if not h: return None, None, ""
    lats = re.findall(r'(?:"lat"|latitude)["\s:=]+(-?[0-9]{2}\.[0-9]{3,})', h, re.I)
    lngs = re.findall(r'(?:"lng"|"lon"|longitude)["\s:=]+(-?[0-9]{2,3}\.[0-9]{3,})', h, re.I)
    img = ""
    m = re.search(r'(https://(?:www\.)?landquest\.com/[^"]+\.(?:jpg|jpeg|webp))', h)
    if m: img = m.group(1)
    try:
        if lats and lngs:
            la, lo = float(lats[0]), float(lngs[0])
            if 48 < la < 61 and -140 < lo < -109:
                return la, lo, img
    except ValueError:
        pass
    return None, None, img

if __name__ == "__main__":
    out_path = "/tmp/landquest.json"
    existing = {}
    if os.path.exists(out_path):
        for r in json.load(open(out_path)):
            existing[r["id"]] = r

    cards = []
    for prov, slug, max_pg in INDEXES:
        for pg in range(1, max_pg + 1):
            url = f"https://www.landquest.com/{slug}/" + (f"?page={pg}" if pg > 1 else "")
            h = curl(url)
            found = CARD_RE.findall(h)
            if not found:
                break
            for path, title, region, lid, price, size in found:
                cards.append({
                    "id": lid, "path": path, "title": title.strip()[:160],
                    "region": region.strip(), "prov": prov,
                    "cad": int(price.replace(",", "")),
                    "acres": parse_size_acres(size),
                })
            print(f"  {prov} p{pg}: {len(found)} cards (total {len(cards)})", file=sys.stderr)
            time.sleep(0.4)

    # dedupe by listing id
    seen, uniq = set(), []
    for c in cards:
        if c["id"] in seen: continue
        seen.add(c["id"]); uniq.append(c)
    print(f"unique: {len(uniq)}", file=sys.stderr)

    results = []
    for i, c in enumerate(uniq):
        if c["id"] in existing and existing[c["id"]].get("lat"):
            prev = existing[c["id"]]
            c["lat"], c["lng"], c["img"] = prev["lat"], prev["lng"], prev.get("img", "")
        else:
            c["lat"], c["lng"], c["img"] = detail_coords(c["path"])
            time.sleep(0.3)
        c["url"] = f"https://www.landquest.com{c.pop('path')}"
        results.append(c)
        if (i + 1) % 25 == 0:
            print(f"  details {i+1}/{len(uniq)}", file=sys.stderr)
            json.dump(results, open(out_path, "w"))

    json.dump(results, open(out_path, "w"))
    with_geo = sum(1 for r in results if r.get("lat"))
    print(f"DONE {len(results)} rows ({with_geo} geocoded) -> {out_path}", file=sys.stderr)
