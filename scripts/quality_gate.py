"""Quality gate: keep only *special* Japan / Austria listings in the app.

The app loads every row in docs/listings.json, and most raw Japan/Austria
listings are ordinary (random farmhouses, inland suburbs). Rows that aren't
special move to data/raw/<country>.json.gz — kept for re-mining, not loaded
by the app. A row stays in the app if ANY of:
  Japan    within 1.5 km of the sea · within 5 km of a ski lift · a Tokyo apartment
           · abandoned ski resorts and any non-SUUMO row (curated sets)
  Austria  within 4 km of a ski lift · within 1 km of a lake · a Vienna apartment
           · any non-willhaben row (the curated JamesEdition alpine set)
Rows already in data/raw are re-checked too, so changing the bar or adding a
new signal can bring them back. Other countries are untouched.

Usage: python3 scripts/quality_gate.py
"""
import gzip, json, os, sys
from collections import Counter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PATH = os.path.join(ROOT, "docs", "listings.json")
RAW_DIR = os.path.join(ROOT, "data", "raw")
GATED = ("Japan", "Austria")

def le(v, x): return v is not None and v <= x

def special(r):
    cf = r.get("cf")
    if cf == "Japan":
        if r.get("tp") == "abandoned_ski" or "suumo.jp" not in (r.get("u") or ""): return True
        return le(r.get("coast_km"), 1.5) or le(r.get("ski_km"), 5) or \
               (r.get("tp") == "apartment" and r.get("rg") == "Tokyo")
    if cf == "Austria":
        if "willhaben" not in (r.get("rb") or ""): return True
        return le(r.get("ski_km"), 4) or le(r.get("lake_km"), 1) or \
               (r.get("tp") == "apartment" and r.get("rg") == "Wien")
    return True

def raw_path(cf): return os.path.join(RAW_DIR, f"{cf.lower()}.json.gz")

def load_raw(cf):
    p = raw_path(cf)
    return json.load(gzip.open(p, "rt", encoding="utf-8")) if os.path.exists(p) else []

def main():
    d = json.load(open(PATH))
    os.makedirs(RAW_DIR, exist_ok=True)
    keep = [r for r in d if r.get("cf") not in GATED]
    report = {}
    for cf in GATED:
        pool = {r["u"]: r for r in load_raw(cf)}
        pool.update({r["u"]: r for r in d if r.get("cf") == cf})      # app rows win (freshest)
        app = [r for r in pool.values() if special(r)]
        raw = [r for r in pool.values() if not special(r)]
        keep += app
        json.dump(raw, gzip.open(raw_path(cf), "wt", encoding="utf-8"), separators=(",", ":"), ensure_ascii=False)
        report[cf] = (len(app), len(raw), Counter(r.get("tp") or "land" for r in app))
    keep.sort(key=lambda x: x.get("r", 0), reverse=True)
    json.dump(keep, open(PATH, "w"), separators=(",", ":"), ensure_ascii=False)
    for cf, (a, rw, kinds) in report.items():
        print(f"{cf}: {a} special rows in the app {dict(kinds)} · {rw} ordinary rows moved to data/raw/", file=sys.stderr)
    print(f"app total: {len(keep)} rows · {os.path.getsize(PATH)/1e6:.1f} MB", file=sys.stderr)

if __name__ == "__main__":
    main()
