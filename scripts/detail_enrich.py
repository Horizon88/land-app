"""Stage-2 enrichment: read detail pages for the *special* candidates only.

Japan (SUUMO) and Austria (willhaben) list pages hide the deal-killers; the
detail page has them. For ski/sea/lake candidates we fetch the detail page
once (cached in data/detail_cache.json, committed) and write onto the row:
  deal   ⛔ hard no's  (leasehold, unbuildable zone, can't rebuild, farmland, no road, green land)
  warn   ⚠ soft flags  (nature-park / cliff rules, narrow road, tenanted, no holiday-home use)
  perks  ✓ positives   (onsen rights, sea / lake / mountain view, ski-in wording)
  imgs   up to 8 photos;  zoning / road / land_cat facts for the detail panel

Usage: python3 scripts/detail_enrich.py [max_new_fetches]
"""
import json, os, re, subprocess, sys, threading
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PATH = os.path.join(ROOT, "docs", "listings.json")
CACHE = os.path.join(ROOT, "data", "detail_cache.json")
MAX_NEW = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

def curl(url, timeout=30):
    try:
        return subprocess.run(["curl", "-skL", "-m", str(timeout), "-A", UA, "-H", "Accept-Language: ja,de,en;q=0.8", url],
                              capture_output=True, text=True, timeout=timeout + 5).stdout
    except Exception:
        return ""

def special(r):
    if r.get("cf") == "Japan":
        return ((r.get("coast_km") is not None and r["coast_km"] <= 1.5) or
                (r.get("ski_km") is not None and r["ski_km"] <= 5)) and r.get("tp") != "apartment"
    if r.get("cf") == "Austria" and "willhaben" in (r.get("rb") or ""):
        return ((r.get("ski_km") is not None and r["ski_km"] <= 4) or
                (r.get("lake_km") is not None and r["lake_km"] <= 1) or r.get("tp") == "apartment")
    return False

# ---------- SUUMO ----------
def field(t, label, n=60):
    i = t.find(label)
    if i < 0: return ""
    s = t[i + len(label): i + len(label) + n].replace("ヒント", "").strip()
    return s

def parse_suumo(h):
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))
    if "販売価格" not in t and "価格" not in t:
        return None
    deal, warn, perks = [], [], []
    tenure = field(t, "土地の権利形態", 20)
    land_cat = field(t, "地目", 12).split(" ")[0]
    zoning = field(t, "用途地域", 16).split(" ")[0]
    road = re.split(r" (?:土地状況|完成時期|住所)", field(t, "私道負担・道路", 40))[0]
    restr = field(t, "その他制限事項", 120)
    if "借地" in tenure: deal.append("leasehold land (借地権)")   # tenure field only — site nav also says 定期借地
    if "市街化調整区域" in t: deal.append("urbanisation-control zone — building generally not allowed (市街化調整区域)")
    if "再建築不可" in t: deal.append("can't be rebuilt (再建築不可)")
    if land_cat.startswith(("田", "畑")):
        if "現況宅地" in land_cat or "現況：宅地" in land_cat:
            warn.append("registered as farmland but currently residential — land-category change needed")
        else:
            deal.append(f"farmland {land_cat} — needs agricultural permit to buy")
    if re.search(r"接道なし|未接道|接道無", t): deal.append("no road access (未接道)")
    if "自然公園法" in restr: warn.append("nature-park rules limit building")
    if "がけ条例" in restr: warn.append("cliff ordinance (がけ条例)")
    if "土砂災害" in t[:60000]: warn.append("landslide hazard zone")
    m = re.search(r"(\d+(?:\.\d+)?)\s*[mｍ]\s*幅", road)
    if m and float(m.group(1)) < 4: warn.append(f"narrow road {m.group(1)} m (setback needed)")
    bc = re.search(r"建ぺい率[･・]容積率\s*(?:ヒント)?\s*(\d+)％", t)
    if bc and int(bc.group(1)) <= 20: warn.append(f"low building coverage {bc.group(1)}%")
    if re.search(r"温泉", t) and not re.search(r"温泉権利はありません|温泉なし|温泉権無", t): perks.append("♨ onsen rights / hot spring")
    if re.search(r"海が見え|海一望|オーシャンビュー|海を望|海を一望|太平洋|相模湾|駿河湾", t): perks.append("🌊 sea view mentioned")
    if re.search(r"富士山が見え|富士山を望|富士山一望", t): perks.append("🗻 Mt Fuji view")
    if re.search(r"眺望良好|眺望良し|眺望抜群|絶景|パノラマ", t): perks.append("🌅 great view (眺望)")
    if re.search(r"スキー場まで徒歩|ゲレンデまで徒歩|ゲレンデ目の前|スキーイン", t): perks.append("⛷ walk to the slopes")
    if "別荘地" in t: perks.append("resort estate (別荘地)")
    imgs = list(dict.fromkeys(re.findall(r"https://img01\.suumo\.com/jj/resizeImage\?src=gazo[^\"'\s>]+?\.jpg", h)))[:8]
    imgs = [i.replace("&amp;", "&") for i in imgs]
    return {"deal": deal, "warn": warn, "perks": perks, "imgs": imgs,
            "zoning": zoning, "land_cat": land_cat, "road": road[:30], "tenure": tenure[:10]}

# ---------- willhaben ----------
def parse_willhaben(h):
    m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    if not m: return None
    try:
        ad = json.loads(m.group(1))["props"]["pageProps"]["advertDetails"]
    except Exception:
        return None
    attrs = {a["name"]: " ".join(a.get("values") or []) for a in ad.get("attributes", {}).get("attribute", [])}
    text = re.sub(r"<[^>]+>", " ", " ".join(v for k, v in attrs.items() if "TEXT" in k or k == "DESCRIPTION"))
    t = text.lower()
    deal, warn, perks = [], [], []
    buildable = re.search(r"bauland(?!erwartung)|wohngebiet|dorfgebiet|kerngebiet|baugrund|bauplatz|bebaubar(?!keit nicht)|baugenehmigung", t)
    t_green = re.sub(r"(?:grenzt|angrenzend|grenzend)[^.]{0,40}(?:grün|frei)land", " ", t)   # bordering open land is not the plot's zoning
    if re.search(r"(?:grenzt|angrenzend|grenzend)[^.]{0,40}(?:grün|frei)land", t): perks.append("🌳 borders open land (privacy)")
    if re.search(r"keine baulandwidmung|nicht bebaubar|kein bauland|landwirtschaftlich gewidmet", t):
        deal.append("not building land (Grünland/Freiland)")
    elif re.search(r"grünland|freiland", t_green):
        (warn.append("part of the plot is Grünland") if buildable else deal.append("not building land (Grünland/Freiland)"))
    if re.search(r"\bbaurecht", t): deal.append("Baurecht — leasehold, not freehold")
    if re.search(r"vermietet|mieter vorhanden|anlegerwohnung|befristet vermietet", t): warn.append("currently tenanted")
    if re.search(r"kein(?:e)? (?:zweit|freizeit)wohnsitz|(?:zweit|freizeit)wohnsitz (?:nicht|unzulässig|verboten)|hauptwohnsitzpflicht|nur hauptwohnsitz", t):
        warn.append("no holiday-home use (Hauptwohnsitz only)")
    if "bauland-aufschließung" in t or "aufschließungsgebiet" in t: warn.append("Aufschließungsgebiet — building release pending")
    if re.search(r"seeblick|blick auf den see|seezugang|seegrund|direkt am see|badeplatz", t): perks.append("🏞 lake view / access")
    if re.search(r"bergblick|panorama|traumblick|fernblick|unverbaubar", t): perks.append("🌅 mountain / panorama view")
    if re.search(r"ski[- ]?in|direkt an der piste|pistennähe|neben der piste|skipiste vor", t): perks.append("⛷ ski-in / by the piste")
    if re.search(r"freizeitwohnsitz (?:möglich|erlaubt|gewidmet)|zweitwohnsitz (?:möglich|erlaubt)|touristische vermietung möglich", t):
        perks.append("✓ holiday-home use allowed")
    imgs = []
    for im in ad.get("advertImageList", {}).get("advertImage", [])[:8]:
        u = im.get("mainImageUrl") or im.get("referenceImageUrl") or im.get("thumbnailImageUrl")
        if u: imgs.append(u)
    widmung = re.search(r"(bauland[- ]?(?:wohngebiet|dorfgebiet|kerngebiet|agrargebiet|betriebsgebiet)?|wohngebiet|dorfgebiet|kerngebiet|gewerbegebiet|grünland|freiland)", t_green)
    return {"deal": deal, "warn": warn, "perks": perks, "imgs": imgs,
            "zoning": widmung.group(1).strip() if widmung else ""}

def enrich_one(u):
    h = curl(u)
    if not h: return u, None
    return u, (parse_suumo(h) if "suumo.jp" in u else parse_willhaben(h))

def main():
    d = json.load(open(PATH))
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    cands = [r for r in d if special(r)]
    todo = [r["u"] for r in sorted(cands, key=lambda r: -(r.get("r") or 0)) if r["u"] not in cache][:MAX_NEW]
    print(f"{len(cands)} special candidates · {len(todo)} detail pages to fetch (cache {len(cache)})", file=sys.stderr)
    lock = threading.Lock(); n = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for u, info in ex.map(enrich_one, todo):
            with lock:
                cache[u] = info or {"failed": True}; n += 1
                if n % 250 == 0:
                    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
                    json.dump(cache, open(CACHE, "w"), ensure_ascii=False, separators=(",", ":"))
                    print(f"  {n}/{len(todo)}", file=sys.stderr)
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump(cache, open(CACHE, "w"), ensure_ascii=False, separators=(",", ":"))
    stats = {"enriched": 0, "deal": 0, "warn": 0, "perks": 0}
    for r in d:
        c = cache.get(r["u"])
        if not c or c.get("failed"): continue
        stats["enriched"] += 1
        for k in ("deal", "warn", "perks"):
            if c.get(k): r[k] = c[k]; stats[k] += 1
            else: r.pop(k, None)
        if c.get("imgs"): r["imgs"] = c["imgs"]
        for k in ("zoning", "land_cat", "road", "tenure"):
            if c.get(k): r[k] = c[k]
        r["detail_checked"] = True
    json.dump(d, open(PATH, "w"), separators=(",", ":"), ensure_ascii=False)
    print(f"applied: {stats}", file=sys.stderr)

if __name__ == "__main__":
    main()
