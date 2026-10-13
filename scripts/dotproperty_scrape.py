"""DotProperty (English, farang-facing Thai portal) — land scrape.

Every search page embeds an `ItemList` JSON-LD with the full record per
listing inline: name, url, description, datePosted, image, address, geo
coords, and offers.price. So we scrape LIST pages only — no per-detail
fetches. Size (rai/sqm) is parsed from the name/description text.

NOTE: DotProperty syndicates a lot of FazWaz inventory (images come from
cdn.fazwaz.com), so the merge dedups against existing rows by coords+price.

Emits /tmp/dotproperty.json for dotproperty_merge.py.
"""
import json, re, subprocess, sys, time, urllib.parse, os

RELAY = "https://landrelay.flag-theory.workers.dev"

# South-Thailand hunt provinces (DotProperty province slugs)
PROVINCES = ["Krabi", "Phuket", "Phang-Nga", "Surat-Thani", "Trang",
             "Nakhon-Si-Thammarat", "Chumphon", "Ranong", "Satun",
             "Prachuap-Khiri-Khan"]
MAX_PAGES = 25   # 30/page → up to 750/province

def via_relay(url, timeout=40):
    api = f"{RELAY}/?url={urllib.parse.quote(url, safe='')}"
    try:
        p = subprocess.run(["curl","-sk","--compressed","-m",str(timeout),api],
                          capture_output=True, timeout=timeout+5)
        return p.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""

def item_list(h):
    for m in re.findall(r'application/ld\+json">(.*?)</script>', h, re.S):
        try:
            d = json.loads(m)
        except Exception:
            continue
        if isinstance(d, dict) and d.get("@type") == "ItemList":
            return d.get("itemListElement", []), d.get("numberOfItems")
    return [], None

def parse_size_sqm(text):
    """Pull a land size in m² from free text (rai + ngan + wah, or sqm)."""
    if not text:
        return None
    t = text.lower().replace(",", "")
    def num(pat):
        m = re.search(r'(\d+(?:\.\d+)?)\s*' + pat, t)
        try: return float(m.group(1)) if m else 0.0
        except (ValueError, AttributeError): return 0.0
    rai  = num(r'rai')
    ngan = num(r'ngan')
    wah  = num(r'(?:sq\.?\s*wah|wah|talang wah)')
    sqm  = num(r'(?:sqm|sq\.?\s*m|square met|m2|ตร\.?ม)')
    total = rai*1600 + ngan*400 + wah*4
    if total >= 40: return round(total, 1)
    if sqm >= 40: return round(sqm, 1)
    return None

if __name__ == "__main__":
    out = {}
    if os.path.exists("/tmp/dotproperty.json"):
        for r in json.load(open("/tmp/dotproperty.json")):
            out[r["url"]] = r
    for prov in PROVINCES:
        seen_prov = 0
        for page in range(1, MAX_PAGES + 1):
            u = f"https://www.dotproperty.co.th/en/land-for-sale/{prov}" + (f"?page={page}" if page > 1 else "")
            h = via_relay(u)
            items, total = item_list(h)
            if not items:
                break
            new = 0
            for el in items:
                it = el.get("item") or {}
                url = it.get("url")
                if not url or url in out:
                    continue
                geo = (it.get("about") or {}).get("geo") or {}
                addr = (it.get("about") or {}).get("address") or {}
                price = None
                off = it.get("offers") or {}
                try: price = int(float(off.get("price"))) if off.get("price") else None
                except Exception: price = None
                desc = it.get("description") or ""
                out[url] = {
                    "url": url, "name": it.get("name", "")[:180],
                    "desc": desc[:600], "datePosted": it.get("datePosted", ""),
                    "img": it.get("image", ""),
                    "province": addr.get("addressRegion") or prov.replace("-", " "),
                    "locality": addr.get("addressLocality", ""),
                    "street": addr.get("streetAddress", ""),
                    "lat": geo.get("latitude"), "lng": geo.get("longitude"),
                    "price_thb": price,
                    "sqm": parse_size_sqm(it.get("name", "") + " " + desc),
                }
                new += 1; seen_prov += 1
            print(f"  {prov:>20} p{page}: {len(items)} items, {new} new (total avail {total})", file=sys.stderr)
            if new == 0:
                break
            json.dump(list(out.values()), open("/tmp/dotproperty.json", "w"))
            time.sleep(0.3)
        print(f"{prov}: {seen_prov} collected", file=sys.stderr)
    json.dump(list(out.values()), open("/tmp/dotproperty.json", "w"))
    sized = sum(1 for r in out.values() if r.get("sqm"))
    coord = sum(1 for r in out.values() if r.get("lat"))
    print(f"TOTAL {len(out)} ({sized} with size, {coord} with coords) -> /tmp/dotproperty.json", file=sys.stderr)
