"""Build docs/countries.json for the country ranking page (docs/countries.html).

Per country:
  - price per acre: median USD/acre of land listings in the app (falls back to
    every listing with an acreage when a country has fewer than 5 land rows)
  - quality of life: UN Human Development Index 2023 (HDR 2025 data file)
  - climate: monthly normals 2016-2025 from the Open-Meteo archive (ERA5),
    averaged over three sample points taken from where that country's listings
    actually are (20th / 50th / 80th percentile of latitude)
  - tax: estimated cost for a foreign individual buying a ~US$1M second home and
    holding it 10 years: one-off purchase taxes + foreign-buyer surcharges + 10x
    annual property/wealth tax, as % of price. Rough, hand-maintained, see TAX.

Usage: python3 scripts/country_stats.py   (climate cached in scripts/geo/climate_cache.json)
"""
import csv, io, json, os, statistics, subprocess, sys, time, urllib.request
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CACHE = os.path.join(ROOT, "scripts", "geo", "climate_cache.json")
HDR_URL = "https://hdr.undp.org/sites/default/files/2025_HDR/HDR25_Composite_indices_complete_time_series.csv"

# HDR country names that differ from the app's
HDR_NAME = {"USA": "United States", "Turkey": "Türkiye"}
# not in the UN data set: plotted with a proxy, flagged in the UI
HDI_PROXY = {"New Caledonia": ("France", "French territory, not in UN data: France's HDI used as a stand-in")}

# purchase = one-off taxes on buying (% of price); foreign = extra levies/licences on
# foreign buyers; annual = recurring property/wealth tax (% of market value per year).
TAX = {
 "Japan":        dict(purchase=4.0, foreign=0,  annual=1.0,  note="acquisition + registration tax on assessed value; fixed-asset + city-planning tax ~1.7% of assessed value/yr"),
 "Canada":       dict(purchase=2.0, foreign=0,  annual=0.6,  note="provincial land transfer tax; federal ban on foreign purchase of homes in cities until 2027 (rural/recreational exempt); BC adds 20% for foreigners in some regions"),
 "USA":          dict(purchase=1.0, foreign=0,  annual=1.1,  note="state/county transfer tax ~0.5-1%; property tax ~1.1%/yr (MA)"),
 "Austria":      dict(purchase=4.6, foreign=0,  annual=0.1,  note="3.5% Grunderwerbsteuer + 1.1% land-register fee; Grundsteuer tiny; EU nationals treated as locals"),
 "Portugal":     dict(purchase=7.0, foreign=0,  annual=0.6,  note="IMT ~6% + 0.8% stamp duty; IMI 0.3-0.45% + AIMI above €600k"),
 "Malaysia":     dict(purchase=4.0, foreign=3,  annual=0.2,  note="foreigners pay 4% flat stamp duty; some states add a foreign levy (e.g. Penang 3%); RM1M+ minimum price for foreigners in most states"),
 "Thailand":     dict(purchase=2.0, foreign=0,  annual=0.1,  note="transfer fee 2% (often split); foreigners cannot own land: condo or 30-yr lease only"),
 "Chile":        dict(purchase=1.5, foreign=0,  annual=0.5,  note="notary + registry; contribuciones ~1% of fiscal value (rural land often exempt)"),
 "Poland":       dict(purchase=2.0, foreign=0,  annual=0.05, note="2% PCC on resale; property tax per m², very low; farmland restricted for non-farmers"),
 "Romania":      dict(purchase=2.0, foreign=0,  annual=0.15, note="notary + registration; building tax ~0.1-0.2%/yr; non-EU buyers cannot own land directly"),
 "Brazil":       dict(purchase=3.5, foreign=0,  annual=0.5,  note="ITBI 2-3% + registry; IPTU/ITR; limits on foreign ownership of rural land"),
 "Indonesia":    dict(purchase=6.0, foreign=0,  annual=0.2,  note="BPHTB 5% + notary; foreigners only via Hak Pakai (right-of-use) or company"),
 "New Zealand":  dict(purchase=0.5, foreign=0,  annual=0.4,  note="no stamp duty or capital-gains tax; council rates; foreigners mostly banned from buying existing homes"),
 "Argentina":    dict(purchase=3.0, foreign=0,  annual=0.3,  note="provincial stamp tax + deed costs; rural land limits for foreigners"),
 "Turkey":       dict(purchase=4.0, foreign=0,  annual=0.3,  note="4% title-deed fee (often split); property tax 0.1-0.6%/yr"),
 "Switzerland":  dict(purchase=2.5, foreign=0,  annual=0.5,  note="cantonal transfer tax + notary; wealth + property tax; Lex Koller caps holiday-home sales to foreigners"),
 "Fiji":         dict(purchase=4.0, foreign=0,  annual=0.5,  note="rough: stamp duty + transfer costs; foreigners barred from freehold land inside town boundaries"),
 "Georgia":      dict(purchase=0.3, foreign=0,  annual=0.1,  note="flat registration fee; property tax 0-1% only above an income threshold; foreigners cannot buy farmland"),
 "New Caledonia":dict(purchase=11.0,foreign=0,  annual=0.2,  note="rough: French-style registration duties + notary (~11%)"),
 "Vanuatu":      dict(purchase=4.0, foreign=0,  annual=0.1,  note="rough: leasehold only (75-yr leases); stamp duty + lease registration; no income or property tax"),
 "Grenada":      dict(purchase=1.0, foreign=10, annual=0.3,  note="Alien Landholding Licence 10% of value for foreigners; buyer stamp duty ~1%"),
 "Australia":    dict(purchase=5.5, foreign=9,  annual=2.0,  note="stamp duty + 8-9% foreign surcharge; land-tax foreign surcharge 2-5%/yr; ban on foreigners buying established homes 2025-27"),
 "France":       dict(purchase=8.0, foreign=0,  annual=0.5,  note="notary + registration ~7.5-8% on resale; taxe foncière; IFI wealth tax above €1.3M"),
 "United Kingdom":dict(purchase=10.0,foreign=8, annual=0.2,  note="Scotland: LBTT up to 12% (~10% effective at £2M) + 8% ADS if you own another home anywhere (reclaimable if it becomes your main home); council tax"),
}

def hdi_table():
    p = os.path.join("/tmp", "hdr25.csv")
    if not os.path.exists(p):
        urllib.request.urlretrieve(HDR_URL, p)
    rows = list(csv.DictReader(open(p, encoding="latin-1")))
    return {r["country"]: float(r["hdi_2023"]) for r in rows if r.get("hdi_2023")}

def climate(lat, lon, cache):
    key = f"{lat:.2f},{lon:.2f}"
    if key in cache: return cache[key]
    url = ("https://archive-api.open-meteo.com/v1/archive?latitude=%.4f&longitude=%.4f"
           "&start_date=2016-01-01&end_date=2025-12-31"
           "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,sunshine_duration,snowfall_sum&timezone=UTC") % (lat, lon)
    for attempt in range(4):
        try:
            d = json.load(urllib.request.urlopen(url, timeout=90))["daily"]; break
        except Exception as e:
            print("  retry", key, e, file=sys.stderr); time.sleep(10 * (attempt + 1))
    else:
        return None
    m = defaultdict(lambda: dict(tmax=[], tmin=[], wet=[], sun=[], snow=[]))
    for i, t in enumerate(d["time"]):
        b = m[int(t[5:7])]
        v = lambda k: d[k][i]
        if v("temperature_2m_max") is None: continue
        b["tmax"].append(v("temperature_2m_max")); b["tmin"].append(v("temperature_2m_min"))
        b["wet"].append(1 if (v("precipitation_sum") or 0) >= 1 else 0)
        b["sun"].append((v("sunshine_duration") or 0) / 3600)
        b["snow"].append(1 if (v("snowfall_sum") or 0) >= 1 else 0)
    out = []
    for mo in range(1, 13):
        b = m[mo]; f = lambda k: round(statistics.mean(b[k]), 2)
        out.append(dict(tmax=f("tmax"), tmin=f("tmin"), wet=round(f("wet") * 30, 1), sun=f("sun"), snow=round(f("snow") * 30, 1)))
    cache[key] = out
    json.dump(cache, open(CACHE, "w"))
    time.sleep(1)
    return out

def main():
    d = json.load(open(os.path.join(ROOT, "docs", "listings.json"))) + \
        json.load(open(os.path.join(ROOT, "docs", "saved_plots.json")))
    hidden = set(json.load(open(os.path.join(ROOT, "docs", "prefs.json"))).get("hidden_countries", []))
    hdi = hdi_table()
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    by = defaultdict(list)
    for r in d:
        if r.get("cf") and r["cf"] not in hidden: by[r["cf"]].append(r)
    out = {"schema": "countries_v1", "built": time.strftime("%Y-%m-%d"),
           "method": __doc__.strip(), "countries": {}}
    for cf, rows in sorted(by.items(), key=lambda kv: -len(kv[1])):
        if cf not in TAX: print("no tax data for", cf, file=sys.stderr); continue
        # compare like with like: tiny building plots always cost more per acre than
        # farmland, so use plots of 0.25-50 acres when a country has enough of them
        allland = [r for r in rows if (r.get("tp") or "land") == "land" and (r.get("ac") or 0) > 0 and (r.get("usd") or 0) > 0]
        band = [r["usd"] / r["ac"] for r in allland if 0.25 <= r["ac"] <= 50]
        skew = False
        if len(band) >= 20:
            land, basis = band, "plots of 0.25-50 acres"
        elif allland:
            land, basis, skew = [r["usd"] / r["ac"] for r in allland], "all land listings (mostly small or few plots: not comparable)", True
        else:
            land = [r["usd"] / r["ac"] for r in rows if (r.get("ac") or 0) > 0 and (r.get("usd") or 0) > 0]
            basis, skew = "estates incl. houses (few listings: not comparable)", True
        if not land: continue
        pts = sorted([r for r in rows if r.get("lat") is not None and r.get("lon") is not None], key=lambda r: r["lat"])
        samples = []
        for q in (0.2, 0.5, 0.8):
            if pts:
                r = pts[min(len(pts) - 1, int(q * len(pts)))]
                if not any(abs(r["lat"] - a) < 0.05 and abs(r["lon"] - b) < 0.05 for a, b in samples):
                    samples.append((round(r["lat"], 3), round(r["lon"], 3)))
        print(f"{cf}: {len(rows)} rows, {len(land)} $/acre, climate at {samples}", file=sys.stderr)
        clim = [c for c in (climate(a, b, cache) for a, b in samples) if c]
        months = [{k: round(statistics.mean(c[i][k] for c in clim), 2) for k in clim[0][i]} for i in range(12)] if clim else None
        name = HDR_NAME.get(cf, cf)
        h, hnote = hdi.get(name), None
        if h is None and cf in HDI_PROXY:
            h, hnote = hdi.get(HDI_PROXY[cf][0]), HDI_PROXY[cf][1]
        t = TAX[cf]
        out["countries"][cf] = {
            "n": len(rows), "n_price": len(land), "price_basis": basis, "price_skew": skew,
            "usd_per_acre": round(statistics.median(land)),
            "usd_per_acre_p25": round(statistics.quantiles(land, n=4)[0]) if len(land) >= 4 else None,
            "usd_per_acre_p75": round(statistics.quantiles(land, n=4)[2]) if len(land) >= 4 else None,
            "hdi": h, "hdi_note": hnote,
            "tax": dict(t, total10=round(t["purchase"] + t["foreign"] + 10 * t["annual"], 1)),
            "climate_points": samples, "months": months,
        }
    json.dump(out, open(os.path.join(ROOT, "docs", "countries.json"), "w"), ensure_ascii=False, indent=1)
    print("wrote docs/countries.json:", len(out["countries"]), "countries", file=sys.stderr)

if __name__ == "__main__":
    main()
