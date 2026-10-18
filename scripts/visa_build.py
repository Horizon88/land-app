"""Build docs/visas.json: entry rules for every passport into the countries on
the ranking page, from the open Passport Index dataset
(github.com/ilyankou/passport-index-dataset, passport-index-tidy.csv).

Codes per passport -> destination:
  number = visa-free for that many days   "vf" = visa-free (no fixed limit, e.g. EU)
  "eta"  = visa-free with an online travel authorisation (ESTA, eTA, UK ETA ...)
  "voa"  = visa on arrival   "ev" = e-visa (apply online)   "req" = visa required
  "own"  = own country
Usage: python3 scripts/visa_build.py
"""
import csv, io, json, os, time, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
URL = "https://raw.githubusercontent.com/ilyankou/passport-index-dataset/master/passport-index-tidy.csv"
NAME = {"USA": "United States", "UAE": "United Arab Emirates"}      # page name -> dataset name
# days allowed under a travel authorisation (dataset gives no number for "eta")
ETA_DAYS = {"United States": 90, "Canada": 180, "United Kingdom": 180, "Australia": 90,
            "New Zealand": 90, "Sri Lanka": 30}
CODE = {"visa free": "vf", "eta": "eta", "visa on arrival": "voa", "e-visa": "ev",
        "visa required": "req", "-1": "own"}

def main():
    rows = list(csv.DictReader(io.StringIO(urllib.request.urlopen(URL, timeout=90).read().decode())))
    page = json.load(open(os.path.join(ROOT, "docs", "countries.json")))["countries"].keys()
    want = {NAME.get(c, c): c for c in page}
    out = {"schema": "visas_v1", "built": time.strftime("%Y-%m-%d"), "source": URL,
           "eta_days": {want[k]: v for k, v in ETA_DAYS.items() if k in want},
           "missing": [c for c in page if NAME.get(c, c) not in {r["Destination"] for r in rows}],
           "passports": {}}
    for r in rows:
        d = want.get(r["Destination"])
        if not d: continue
        req = r["Requirement"].strip()
        out["passports"].setdefault(r["Passport"], {})[d] = int(req) if req.isdigit() else CODE.get(req, req)
    json.dump(out, open(os.path.join(ROOT, "docs", "visas.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"visas.json: {len(out['passports'])} passports x {len(want)} destinations; missing {out['missing']}")

if __name__ == "__main__":
    main()
