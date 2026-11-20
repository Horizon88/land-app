"""Swipe deck for the Land Command Center pipeline (Google Sheet 'Land Command Center').

data/pipeline.json is an export of the sheet's Pipeline tab (a session with the Google Drive
connector refreshes it). This turns each lead into a swipe card in docs/family/leads.json, in the
same shape as the listing deck: satellite views of the spot, the stage, why it matters, the main
blocker and the next action. Swipes travel like listing swipes (ntfy -> family_sync.py ->
docs/family/state.json), keyed by the lead ID, so they can be copied back into the sheet's
Ed / Siri swipe columns.

Usage: python3 scripts/leads_deck.py
"""
import json, math, os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

def aerial(lat, lon, w_km):
    dx = w_km / 2 / (111.32 * math.cos(math.radians(lat))); dy = w_km * 0.72 / 2 / 110.57
    return ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?"
            f"bbox={lon-dx:.5f},{lat-dy:.5f},{lon+dx:.5f},{lat+dy:.5f}&bboxSR=4326&imageSR=3857&size=900,640&format=jpg&f=image")

def main():
    rows = json.load(open(os.path.join(ROOT, "data", "pipeline.json")))
    cards = []
    for r in rows:
        if str(r.get("stage", "")).startswith(("8", "x")): continue
        try: lat, lon = float(r["lat"]), float(r["lon"])
        except Exception: continue
        sat = [aerial(lat, lon, 0.8), aerial(lat, lon, 4)]
        app = r.get("link", "") if "land-app" in r.get("link", "") else ""
        cards.append({"code": r["id"], "lead": True, "u": r.get("link") or "", "cf": r.get("strategy", ""), "rg": r.get("region", ""),
                      "a": r.get("region", ""), "tp": "lead", "name": r.get("name", "")[:140], "usd": None, "stage": r.get("stage", ""),
                      "ask": r.get("ask", ""), "owner": r.get("lead", ""), "seller": r.get("seller", ""),
                      "perks": [x for x in (r.get("key"), f"Next: {r.get('next')}" if r.get("next") else "", f"Seller / owner: {r.get('seller')}" if r.get("seller") else "") if x],
                      "warn": [x for x in (r.get("blocker"), f"Evidence: {r.get('grade')}" if r.get("grade") else "") if x],
                      "img": sat[0], "photos": sat[1:], "sat": True, "lat": lat, "lon": lon, "app": app})
    json.dump({"built": __import__("time").strftime("%Y-%m-%d"), "cards": cards}, open(os.path.join(ROOT, "docs", "family", "leads.json"), "w"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"leads deck: {len(cards)} cards", file=__import__("sys").stderr)

if __name__ == "__main__":
    main()
