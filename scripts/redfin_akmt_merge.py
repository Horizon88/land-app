"""Merge the Alaska + Montana Redfin crawl (/tmp/redfin_akmt.json) into listings.json.

Same scoring as redfin_us_merge.py, with its own source tag, so re-running it
replaces only these rows. Keeps what the user wants from these two states:
oceanfront (≤1.5 km), ski (≤5 km from a lift), or big land: 5+ acres, bare or
with a house. Listings already in the main US crawl are skipped.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import redfin_us_merge as m

BIG_ACRES = 5

def special(r):
    c, s = r.get("coast_km"), r.get("ski_km")
    return (c is not None and c <= 1.5) or (s is not None and s <= 5) or (r.get("ac") or 0) >= BIG_ACRES

if __name__ == "__main__":
    m.RAW = "/tmp/redfin_akmt.json"
    m.SRC = "src:redfin-akmt"
    m.REST = os.path.join(m.ROOT, "data", "raw", "redfin_akmt_rest.json.gz")
    m.SPECIAL = special
    m.main()
