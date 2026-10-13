"""Merge BAM detail data into listings.json — v2.

BAM is NPA (foreclosed bank assets) so every row is forced-sale (distress +30).
Filter to land + condo + commercial. Skip houses/townhouses (covered elsewhere,
and they don't help the land-hunt thesis). Use real province_name / city_name /
gps coords / col_typedesc from the structured asset record."""
import json, math, sys
from collections import Counter

USD_PER_THB = 1/36.0

raw = json.load(open("/tmp/bam_full.json"))
print(f"raw BAM rows: {len(raw)}", file=sys.stderr)

# Asset type → tp (we model in our schema)
# Use npa_type when available, fall back to col_typedesc.
ASSET_TYPE_TO_TP = {
    "ที่ดิน": "land",
    "ที่ดินเปล่า": "land",
    "ที่ดินพร้อมสิ่งปลูกสร้าง": "land",   # land-with-building — still useful (buy land, demo / rebuild)
    "ห้องชุด": "apartment",
    "อาคารชุด": "apartment",
    "คอนโดมิเนียม": "apartment",
    "อาคารพาณิชย์": "commercial",
}

# Province (Thai → English) — top 20 BAM provinces
PROV_EN = {
    "กรุงเทพมหานคร":"Bangkok","ปทุมธานี":"Pathum Thani","นนทบุรี":"Nonthaburi",
    "สมุทรปราการ":"Samut Prakan","สมุทรสาคร":"Samut Sakhon","สมุทรสงคราม":"Samut Songkhram",
    "ภูเก็ต":"Phuket","ชลบุรี":"Chonburi","เชียงใหม่":"Chiang Mai","เชียงราย":"Chiang Rai",
    "สุราษฎร์ธานี":"Surat Thani","กระบี่":"Krabi","พังงา":"Phang Nga",
    "ประจวบคีรีขันธ์":"Prachuap Khiri Khan","เพชรบุรี":"Phetchaburi","ระยอง":"Rayong",
    "ตราด":"Trat","จันทบุรี":"Chanthaburi","ฉะเชิงเทรา":"Chachoengsao",
    "นครราชสีมา":"Nakhon Ratchasima","ขอนแก่น":"Khon Kaen","อุดรธานี":"Udon Thani",
    "อุบลราชธานี":"Ubon Ratchathani","เลย":"Loei","นครศรีธรรมราช":"Nakhon Si Thammarat",
    "สงขลา":"Songkhla","ตรัง":"Trang","พัทลุง":"Phatthalung",
    "นครปฐม":"Nakhon Pathom","อยุธยา":"Ayutthaya","พระนครศรีอยุธยา":"Ayutthaya","สระบุรี":"Saraburi",
    "อ่างทอง":"Ang Thong","สิงห์บุรี":"Sing Buri","ชัยนาท":"Chai Nat",
    "สุพรรณบุรี":"Suphan Buri","นครนายก":"Nakhon Nayok","ปราจีนบุรี":"Prachin Buri",
    "สระแก้ว":"Sa Kaeo","บุรีรัมย์":"Buri Ram","สุรินทร์":"Surin","ศรีสะเกษ":"Si Sa Ket",
    "ลพบุรี":"Lopburi","กาญจนบุรี":"Kanchanaburi","ราชบุรี":"Ratchaburi",
    "นครสวรรค์":"Nakhon Sawan","พิษณุโลก":"Phitsanulok","พิจิตร":"Phichit",
    "สุโขทัย":"Sukhothai","อุตรดิตถ์":"Uttaradit","ลำปาง":"Lampang","ลำพูน":"Lamphun",
    "แม่ฮ่องสอน":"Mae Hong Son","น่าน":"Nan","แพร่":"Phrae","ตาก":"Tak",
    "ชุมพร":"Chumphon","ระนอง":"Ranong","สตูล":"Satun","ยะลา":"Yala",
    "นราธิวาส":"Narathiwat","ปัตตานี":"Pattani",
}

SIZE_TIERS = [(0.1,-25),(0.25,-12),(0.5,0),(1,6),(2.5,14),(5,22),(10,32),(25,44),(50,56),(100,68),(500,80),(float("inf"),92)]
def size_bonus(ac):
    for t,b in SIZE_TIERS:
        if ac < t: return b
    return 92

rows = []
n_skipped_type = 0
n_skipped_no_coord = 0
n_skipped_small = 0
type_counts = Counter()

for r in raw:
    at = (r.get("asset_type") or "").strip()
    type_counts[at] += 1
    if at not in ASSET_TYPE_TO_TP:
        n_skipped_type += 1
        continue
    if not (r.get("lat") and r.get("lng")):
        n_skipped_no_coord += 1
        continue
    tp = ASSET_TYPE_TO_TP[at]
    price_thb = r["price_thb"]
    usd = round(price_thb * USD_PER_THB)
    sqm_land = r.get("sqm_land") or 0
    sqm_usable = r.get("sqm_usable") or 0
    sqm = r.get("sqm") or sqm_land or sqm_usable
    # Land-area in acres (only meaningful for land tp; for condo we use sqm interior)
    ac = round(sqm_land / 4046.86, 3) if sqm_land else 0
    if tp == "land" and ac < 0.05:  # require ≥200 sqm of land
        n_skipped_small += 1
        continue
    if tp == "apartment" and (not sqm_usable or sqm_usable < 18):
        n_skipped_small += 1
        continue
    upm = round(usd / sqm, 1) if sqm else 0

    # Score
    rb = ["src:bam"]
    score = 16; rb.append("acc+16")
    if tp == "land":
        sb = size_bonus(ac); score += sb; rb.append(f"size{'+' if sb>=0 else ''}{sb}")
    # Forced-sale (BAM is the bank-asset-management arm)
    score += 30; rb.append("forced-sale+30")
    # Grade A → +3, B → 0, C → -2
    grade = r.get("grade") or ""
    if grade == "A": score += 3; rb.append("grade-A+3")
    elif grade == "C": score -= 2; rb.append("grade-C-2")
    # Foreign-friction
    if tp == "land":
        score -= 25; rb.append("foreign_th_land-25")
    elif tp == "apartment":
        score -= 5; rb.append("foreign_th_condo-5")  # 49% foreign quota
    elif tp == "commercial":
        score -= 25; rb.append("foreign_th_comm-25")

    prov = r.get("province") or ""
    prov_en = PROV_EN.get(prov, prov or "Thailand")
    dist = r.get("district") or ""
    bedroom = r.get("bedroom")
    bathroom = r.get("bathroom")

    name = (r.get("name") or "").strip()[:140]
    img = r.get("img") or ""

    rows.append({
        "tp": tp, "cf": "Thailand",
        "r": round(score, 1),
        "rg": prov_en, "a": dist[:30],
        "ac": ac, "m2": int(round(sqm)) if sqm else 0,
        "usd": usd, "upm": upm,
        "v": "", "el": "",
        "t": "Freehold" if tp == "apartment" else "Chanote (Thai)",
        "lat": r["lat"], "lon": r["lng"],
        "cur": "THB", "lp": str(price_thb),
        "rb": "+".join(rb),
        "img": img, "imgs": [img] if img else [],
        "u": r["url"],
        "apt": "", "apt_km": None,
        "name": name,
        "bed": bedroom, "bath": bathroom,
        "distress": min(100, 30 + 5),
        "distress_breakdown": [("forced-sale feed (BAM NPL)", 30), ("Thai land in BAM inventory", 5)],
        "foreign_friction": -25 if tp == "land" else (-5 if tp == "apartment" else -25),
        "foreign_note": "BAM-disposed Thai property" + (" (foreigners need company structure for land)" if tp == "land" else (" (49% foreign quota for condos)" if tp == "apartment" else "")),
        "npa": True,
        "grade": grade,
    })

print(f"type counts: {type_counts.most_common()}", file=sys.stderr)
print(f"skipped: non-matching-type={n_skipped_type} no-coord={n_skipped_no_coord} too-small={n_skipped_small}", file=sys.stderr)
print(f"keeping: {len(rows)}", file=sys.stderr)

# Merge: strip prior BAM rows (any bam.co.th URL or src:bam tag — covers
# legacy /en/npa rows from the first scraper too).
existing = json.load(open("/home/user/land-app/docs/listings.json"))
def is_bam(e):
    return "src:bam" in (e.get("rb","") or "") or "bam.co.th" in (e.get("u","") or "")
existing = [e for e in existing if not is_bam(e)]
existing_urls = {e.get("u") for e in existing}
rows = [r for r in rows if r["u"] not in existing_urls]
merged = existing + rows
merged.sort(key=lambda r: r.get("r",0), reverse=True)
json.dump(merged, open("/home/user/land-app/docs/listings.json","w"))
print(f"merged: {len(rows)} new BAM rows; total {len(merged)}", file=sys.stderr)

by_tp = Counter(r["tp"] for r in rows)
print(f"by type: {by_tp.most_common()}", file=sys.stderr)
top = sorted(rows, key=lambda r: r.get("r",0), reverse=True)[:10]
print("\nTOP 10 BAM:", file=sys.stderr)
for r in top:
    print(f"  ★{r['r']:>5}  {r['tp']:>9}  ${r['usd']:>9,}  {r['ac']:>6}ac  {r['rg']:<14}  {r['name'][:50]}", file=sys.stderr)
