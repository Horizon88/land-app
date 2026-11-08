"""Redfin: Alaska and Montana land + homes on land.

Reuses the gis-csv crawl in redfin_us_scrape.py over wider regions than the
ski/coast list: Alaska's coast towns (Kachemak Bay, Seward, Southeast), the
Kenai and Mat-Su valleys, Girdwood, Fairbanks; Montana's ski towns, Flathead
Lake, the Bitterroot, Paradise and Madison valleys, Seeley-Swan, Red Lodge.
Emits /tmp/redfin_akmt.json for redfin_akmt_merge.py.

Usage: python3 scripts/redfin_akmt_scrape.py [region-substring ...]
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import redfin_us_scrape as rf

# name, kind, bbox (west, south, east, north)
REGIONS = [
    # --- Alaska
    ("Homer-Kachemak Bay AK", "coast", (-151.95, 59.50, -151.15, 59.85)),
    ("Anchor Point-Ninilchik AK", "coast", (-151.95, 59.85, -151.25, 60.15)),
    ("Kenai-Soldotna-Sterling AK", "wild", (-151.45, 60.30, -150.30, 60.70)),
    ("Cooper Landing-Moose Pass AK", "wild", (-150.30, 60.35, -149.30, 60.60)),
    ("Seward AK", "coast", (-149.55, 59.95, -149.25, 60.25)),
    ("Girdwood-Alyeska AK", "ski", (-149.25, 60.90, -149.00, 61.02)),
    ("Anchorage Hillside AK", "wild", (-149.85, 61.00, -149.55, 61.20)),
    ("Mat-Su Valley AK", "wild", (-150.30, 61.40, -148.90, 61.85)),
    ("Willow-Talkeetna AK", "wild", (-150.35, 61.75, -149.85, 62.40)),
    ("Fairbanks-Ester AK", "wild", (-148.30, 64.70, -147.30, 65.05)),
    ("Juneau AK", "coast", (-134.85, 58.25, -134.30, 58.55)),
    ("Sitka AK", "coast", (-135.50, 56.95, -135.20, 57.15)),
    ("Ketchikan AK", "coast", (-131.90, 55.25, -131.40, 55.60)),
    ("Haines-Skagway AK", "coast", (-135.60, 59.10, -135.20, 59.50)),
    ("Kodiak AK", "coast", (-152.75, 57.55, -152.25, 57.90)),
    ("Valdez-Cordova AK", "coast", (-146.50, 60.50, -145.60, 61.15)),
    ("Petersburg-Wrangell AK", "coast", (-133.10, 56.30, -132.30, 56.85)),
    # --- Montana
    ("Whitefish-Columbia Falls MT", "ski", (-114.60, 48.25, -113.90, 48.65)),
    ("Flathead Lake MT", "lake", (-114.45, 47.60, -113.95, 48.15)),
    ("Swan-Seeley Valley MT", "wild", (-113.95, 47.05, -113.40, 47.75)),
    ("Bitterroot Valley MT", "wild", (-114.30, 45.85, -113.95, 46.60)),
    ("Missoula MT", "wild", (-114.25, 46.75, -113.85, 47.05)),
    ("Big Sky-Gallatin Canyon MT", "ski", (-111.50, 45.15, -111.05, 45.55)),
    ("Bozeman-Bridger MT", "ski", (-111.20, 45.55, -110.85, 45.90)),
    ("Paradise Valley-Livingston MT", "wild", (-110.90, 45.10, -110.40, 45.75)),
    ("Madison Valley-Ennis MT", "wild", (-111.90, 44.85, -111.45, 45.45)),
    ("Red Lodge MT", "ski", (-109.45, 45.05, -109.10, 45.30)),
    ("Philipsburg-Georgetown Lake MT", "ski", (-113.45, 46.10, -113.05, 46.40)),
    ("Lake Koocanusa-Eureka MT", "lake", (-115.40, 48.60, -114.90, 49.00)),
    ("Libby-Troy MT", "wild", (-116.05, 48.25, -115.40, 48.55)),
    ("Polson-Mission Valley MT", "wild", (-114.30, 47.25, -113.95, 47.70)),
]

if __name__ == "__main__":
    rf.REGIONS = REGIONS
    rf.OUT = "/tmp/redfin_akmt.json"
    rf.main(sys.argv[1:])
