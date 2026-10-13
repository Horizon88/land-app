"""Deep FazWaz sweep of the farang coast — pages 1-10 per province (the
original scrape stopped at 3), targeting the company-held/Chanote hunt.
Only fetches details for listings NOT already in listings.json.

Emits /tmp/fazwaz_deep.json for fazwaz_deep_merge.py.
"""
import json, sys, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fazwaz_south_th_scrape import via_relay, parse_list_urls, parse_detail

SLUGS = [
    ("Koh Samui (Surat Thani)", "koh-samui",   9.51, 100.02),
    ("Koh Phangan",             "koh-phangan", 9.75, 100.03),
    ("Surat Thani",             "surat-thani", 9.13,  99.33),
    ("Phuket",                  "phuket",      7.90,  98.36),
    ("Krabi",                   "krabi",       8.06,  98.92),
    ("Phang Nga",               "phang-nga",   8.45,  98.53),
    ("Koh Lanta",               "koh-lanta",   7.63,  99.08),
]

if __name__ == "__main__":
    have = {r.get("u") for r in json.load(open("/home/user/land-app/docs/listings.json"))}
    out_path = "/tmp/fazwaz_deep.json"
    results = json.load(open(out_path)) if os.path.exists(out_path) else []
    done = {r["url"] for r in results}

    todo = []
    for prov, slug, lat0, lng0 in SLUGS:
        seen = set()
        for page in range(1, 11):
            u = f"https://www.fazwaz.com/land-for-sale/thailand/{slug}"
            if page > 1: u += f"?page={page}"
            body = via_relay(u, timeout=30)
            if not body or len(body) < 30000: break
            urls = parse_list_urls(body)
            new = [x for x in urls if x not in seen]
            seen.update(new)
            fresh = [x for x in new if x not in have and x not in done]
            todo.extend((x, prov, lat0, lng0) for x in fresh)
            print(f"  {prov:>24} p{page}: {len(urls)} listed, {len(fresh)} new-to-us", file=sys.stderr)
            if len(new) == 0: break
            time.sleep(0.3)

    print(f"\n{len(todo)} new detail pages to fetch", file=sys.stderr)
    for i, (u, prov, lat0, lng0) in enumerate(todo):
        p = parse_detail(u, timeout=30)
        if p:
            p["province"] = prov
            if not p.get("lat"):
                p["lat"], p["lng"] = lat0, lng0
            results.append(p)
        if (i + 1) % 25 == 0:
            json.dump(results, open(out_path, "w"))
            print(f"  {i+1}/{len(todo)}", file=sys.stderr)
        time.sleep(0.2)
    json.dump(results, open(out_path, "w"))
    print(f"DONE {len(results)} rows -> {out_path}", file=sys.stderr)
