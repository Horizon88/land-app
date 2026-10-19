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
HDR_NAME = {"USA": "United States", "Turkey": "Türkiye", "UAE": "United Arab Emirates", "Vietnam": "Viet Nam"}
# not in the UN data set: plotted with a proxy, flagged in the UI
HDI_PROXY = {"New Caledonia": ("France", "French territory, not in UN data: France's HDI used as a stand-in")}

# purchase = one-off taxes on buying (% of price); foreign = extra levies/licences on
# foreign buyers; annual = recurring property/wealth tax (% of market value per year).
TAX = {
 "Japan":        dict(purchase=4.0, foreign=0,  annual=1.0,  note="acquisition + registration tax on assessed value; fixed-asset + city-planning tax ~1.7% of assessed value/yr"),
 "Canada":       dict(purchase=2.0, foreign=20, annual=0.6,  note="provincial land transfer tax ~2%; foreign buyers: BC +20% (Metro Vancouver, Victoria, Fraser Valley, Okanagan, Nanaimo), Ontario +25% province-wide; BC speculation & vacancy tax 2%/yr for foreign owners in those areas; federal ban on foreigners buying homes until 2027 (rural areas exempt); federal 1% underused-housing tax reportedly repealed from 2025; non-residents: 25% withholding on rent and a s.116 certificate when selling"),
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
 "New Zealand":  dict(purchase=0.5, foreign=0,  annual=0.4,  note="no stamp duty or capital-gains tax (2-yr bright-line on homes); FOREIGNERS CANNOT BUY HOMES except Australians/Singaporeans or Active Investor Plus visa holders (one home worth NZ$5M+, law passed Dec 2025); rural/sensitive land needs Overseas Investment Office consent"),
 "Argentina":    dict(purchase=3.0, foreign=0,  annual=0.3,  note="provincial stamp tax + deed costs; rural land limits for foreigners"),
 "Turkey":       dict(purchase=4.0, foreign=0,  annual=0.3,  note="4% title-deed fee (often split); property tax 0.1-0.6%/yr"),
 "Switzerland":  dict(purchase=2.5, foreign=0,  annual=0.5,  note="cantonal transfer tax + notary; wealth + property tax; Lex Koller caps holiday-home sales to foreigners"),
 "Fiji":         dict(purchase=1.0, foreign=0,  annual=0.1,  note="stamp duty abolished Aug 2020 (legal/registration costs only); 10% capital gains tax when you sell; foreigners can't buy residential land inside town boundaries and must build (FJD 250k+) on vacant residential land within 2 yrs; 12.5% VAT on some sales"),
 "Georgia":      dict(purchase=0.3, foreign=0,  annual=0.1,  note="flat registration fee; property tax 0-1% only above an income threshold; foreigners cannot buy farmland"),
 "New Caledonia":dict(purchase=11.0,foreign=0,  annual=0.2,  note="rough: French-style registration duties + notary (~11%)"),
 "Vanuatu":      dict(purchase=4.0, foreign=0,  annual=0.1,  note="rough: leasehold only (75-yr leases); stamp duty + lease registration; no income or property tax"),
 "Grenada":      dict(purchase=1.0, foreign=10, annual=0.3,  note="Alien Landholding Licence 10% of value for foreigners; buyer stamp duty ~1%"),
 "Australia":    dict(purchase=5.5, foreign=9,  annual=2.0,  note="stamp duty + 8-9% foreign surcharge; land-tax foreign surcharge 2-5%/yr; ban on foreigners buying established homes 2025-27"),
 "France":       dict(purchase=8.0, foreign=0,  annual=0.5,  note="notary + registration ~7.5-8% on resale; taxe foncière; IFI wealth tax above €1.3M"),
 "South Africa": dict(purchase=10.0,foreign=0,  annual=0.6,  note="transfer duty up to 13% above ~R12M; municipal rates; register foreign funds with the Reserve Bank to repatriate later"),
 "Italy":        dict(purchase=9.0, foreign=0,  annual=0.5,  note="9% registration tax on a second-home resale (on cadastral value); IMU on second homes"),
 "Spain":        dict(purchase=8.0, foreign=0,  annual=0.4,  note="ITP 6-10% by region on resale; IBI; regional wealth tax"),
 "Greece":       dict(purchase=3.5, foreign=0,  annual=0.2,  note="3% transfer tax + fees; ENFIA"),
 "Croatia":      dict(purchase=3.0, foreign=0,  annual=0.1,  note="3% transfer tax; holiday-home property tax since 2025"),
 "Montenegro":   dict(purchase=3.0, foreign=0,  annual=0.25, note="3% transfer tax"),
 "Cyprus":       dict(purchase=4.0, foreign=0,  annual=0.0,  note="land-registry transfer fees 3-8% (halved on resale without VAT); no annual property tax; non-EU buyers need a permit"),
 "Malta":        dict(purchase=5.0, foreign=0,  annual=0.0,  note="5% stamp duty; no property tax; non-EU buyers need an AIP permit outside special designated areas"),
 "UAE":          dict(purchase=4.0, foreign=0,  annual=0.0,  note="Dubai Land Department 4%; no property tax"),
 "Panama":       dict(purchase=2.0, foreign=0,  annual=0.7,  note="2% transfer tax; property tax 0.5-1% above exemptions"),
 "Costa Rica":   dict(purchase=3.5, foreign=0,  annual=0.25, note="1.5% transfer + stamps/registry; 0.25% municipal; luxury-home tax"),
 "Mexico":       dict(purchase=3.0, foreign=0,  annual=0.1,  note="acquisition tax 2-4%; within 50 km of the coast foreigners buy through a bank trust (fideicomiso)"),
 "Uruguay":      dict(purchase=2.5, foreign=0,  annual=0.5,  note="2% transfer tax + fees; contribución inmobiliaria; small wealth tax"),
 "Philippines":  dict(purchase=3.0, foreign=0,  annual=1.0,  note="documentary stamp + transfer + registration; foreigners cannot own land (condos only)"),
 "Vietnam":      dict(purchase=0.5, foreign=0,  annual=0.05, note="0.5% registration fee; foreigners cannot own land, apartments on 50-year terms"),
 "Sri Lanka":    dict(purchase=4.0, foreign=0,  annual=0.2,  note="4% stamp duty; foreigners cannot own land freehold (leases up to 99 yrs)"),
 "Mauritius":    dict(purchase=5.0, foreign=0,  annual=0.0,  note="5% registration duty; foreigners buy through approved schemes (IRS/PDS/smart city)"),
 "Bahamas":      dict(purchase=10.0,foreign=0,  annual=0.75, note="10% VAT/stamp on transfers (often split); real-property tax up to 1%"),
 "Norway":       dict(purchase=2.5, foreign=0,  annual=0.3,  note="2.5% document duty; municipal property tax; wealth tax ~1%"),
 "Sweden":       dict(purchase=1.5, foreign=0,  annual=0.1,  note="1.5% stamp duty; property fee capped (~SEK 9,500/yr)"),
 "Ireland":      dict(purchase=1.5, foreign=0,  annual=0.1,  note="stamp duty 1% up to €1M, 2% above; Local Property Tax"),
 "Slovenia":     dict(purchase=2.0, foreign=0,  annual=0.1,  note="2% transfer tax"),
 "Bulgaria":     dict(purchase=3.0, foreign=0,  annual=0.15, note="transfer tax 0.1-3% + notary; non-EU buyers cannot own land directly"),
 "Albania":      dict(purchase=1.0, foreign=0,  annual=0.1,  note="low transfer costs; agricultural land restricted for foreigners"),
 "Morocco":      dict(purchase=6.0, foreign=0,  annual=0.3,  note="4% registration + 1.5% land registry + notary"),
 "Colombia":     dict(purchase=3.0, foreign=0,  annual=0.8,  note="registration + notary ~3%; predial 0.5-1.2%"),
 "Dominican Republic":dict(purchase=3.0,foreign=0,annual=0.5, note="3% transfer tax; IPI 1% above an exemption"),
 "Germany":      dict(purchase=7.5, foreign=0,  annual=0.3,  note="land transfer tax 3.5-6.5% + notary ~2%; Grundsteuer"),
 "Andorra":      dict(purchase=4.0, foreign=0,  annual=0.1,  note="4% transfer tax; foreign buyers need an investment authorisation"),
 "United Kingdom":dict(purchase=10.0,foreign=8, annual=0.2,  note="Scotland: LBTT up to 12% (~10% effective at £2M) + 8% ADS if you own another home anywhere (reclaimable if it becomes your main home); council tax"),
}

# Personal income tax for a resident (2026, rough; confirm with a local adviser).
# top = top marginal rate on income earned in the country (national + typical local).
# abroad = long-run rate on foreign income (investments, remote work) for a resident;
#          0 = territorial / remittance-exempt. Temporary new-arrival breaks are in the note.
INCOME = {
 "Japan":         dict(top=55, abroad=55, note="45% national + 10% local. Non-permanent residents (first 5 of 10 yrs) only pay on foreign income they bring into Japan."),
 "Canada":        dict(top=53.5, abroad=53.5, note="federal + provincial (BC/ON ~53.5%); worldwide income."),
 "USA":           dict(top=42, abroad=42, note="37% federal + state (MA 9% over $1M, UT 4.65%); worldwide income. US citizens pay this wherever they live."),
 "Austria":       dict(top=55, abroad=27.5, note="50% above ~€100k, 55% above €1M; capital income 27.5% flat; worldwide."),
 "Portugal":      dict(top=53, abroad=28, note="48% + 5% solidarity; 28% flat on investment income. IFICI ('NHR 2.0'): 20% on qualifying jobs and most foreign income exempt for 10 yrs, if you qualify."),
 "Malaysia":      dict(top=30, abroad=0, note="foreign income brought in by individuals is exempt until end-2036."),
 "Thailand":      dict(top=35, abroad=35, note="since 2024, foreign income is taxed if brought into Thailand (not if kept abroad). LTR-visa holders: foreign income exempt."),
 "Chile":         dict(top=40, abroad=40, note="foreigners pay only on Chilean income for their first 3 years, then worldwide."),
 "Poland":        dict(top=36, abroad=19, note="32% + 4% solidarity above PLN 1M; 19% on capital income; 19% flat option for business income."),
 "Romania":       dict(top=10, abroad=10, note="10% flat income tax (plus health contributions); dividends 16%."),
 "Brazil":        dict(top=27.5, abroad=15, note="27.5% on salary; 15% on offshore investments since 2024; new minimum tax on high earners from 2026."),
 "Indonesia":     dict(top=35, abroad=35, note="worldwide; skilled expats can elect Indonesian-income-only for the first 4 years."),
 "New Zealand":   dict(top=39, abroad=39, note="new residents: most foreign income exempt for the first 4 years; no capital-gains tax."),
 "Argentina":     dict(top=35, abroad=35, note="worldwide; plus an annual wealth tax (bienes personales)."),
 "Turkey":        dict(top=40, abroad=40, note="worldwide for residents."),
 "Switzerland":   dict(top=40, abroad=40, note="varies a lot by canton (Zug ~22%, Zurich ~40%); non-working foreigners can negotiate lump-sum (forfait) taxation in many cantons."),
 "Fiji":          dict(top=39, abroad=39, note="residents: 0% to FJD 30k, 18-20% to FJD 270k, then 33-39% (39% above FJD 1M); non-residents 20% from the first dollar. Dividends untaxed since 2017; 10% CGT on gains, for residents also on foreign assets. Workers on contracts of up to 3 yrs: foreign income exempt."),
 "Georgia":       dict(top=20, abroad=0, note="20% flat; foreign income exempt (territorial); 1% turnover tax for small businesses."),
 "New Caledonia": dict(top=40, abroad=40, note="rough: own territorial income tax, top ~40%."),
 "Vanuatu":       dict(top=0, abroad=0, note="no personal income tax."),
 "Grenada":       dict(top=28, abroad=28, note="rough: top rate 28%."),
 "Australia":     dict(top=47, abroad=47, note="45% + 2% Medicare; temporary-visa residents don't pay on foreign income."),
 "France":        dict(top=49, abroad=30, note="45% + 4% high-income surcharge; ~30% flat on investment income; impatriate regime for workers moving in."),
 "South Africa":  dict(top=45, abroad=45, note="worldwide; dividends 20%, capital gains effectively up to ~18%."),
 "Italy":         dict(top=47, abroad=26, note="26% on investment income. New residents can pay a flat €200k/yr on ALL foreign income for 15 yrs; 7% flat for foreign pensioners in small southern towns."),
 "Spain":         dict(top=47, abroad=28, note="savings income 19-30%. Beckham law: 24% on Spanish work income, foreign income exempt, for 6 yrs. Regional wealth tax."),
 "Greece":        dict(top=44, abroad=44, note="non-dom option: flat €100k/yr on all foreign income (needs €500k investment); 7% flat for foreign pensioners; half-tax for relocating workers."),
 "Croatia":       dict(top=30, abroad=12, note="top rate 30-33% depending on city; 12% on capital income."),
 "Montenegro":    dict(top=15, abroad=15, note="9-15% progressive."),
 "Cyprus":        dict(top=35, abroad=0,  note="non-dom residents: 0% on dividends and interest for 17 years; foreign pensions 5%."),
 "Malta":         dict(top=35, abroad=0,  note="non-domiciled residents pay nothing on foreign income they keep abroad (minimum €5k tax)."),
 "UAE":           dict(top=0,  abroad=0,  note="no personal income tax."),
 "Panama":        dict(top=25, abroad=0,  note="territorial: foreign income not taxed."),
 "Costa Rica":    dict(top=25, abroad=0,  note="territorial: foreign income not taxed."),
 "Mexico":        dict(top=35, abroad=35, note="worldwide for residents."),
 "Uruguay":       dict(top=36, abroad=12, note="12% on foreign dividends/interest, but new residents get an 11-year holiday on foreign investment income."),
 "Philippines":   dict(top=35, abroad=0,  note="resident foreigners are taxed only on Philippine income."),
 "Vietnam":       dict(top=35, abroad=35, note="worldwide for residents."),
 "Sri Lanka":     dict(top=36, abroad=36, note="worldwide for residents."),
 "Mauritius":     dict(top=35, abroad=0,  note="0-20% bands + 15% 'fair share' surcharge on very high incomes; foreign income taxed only if brought in."),
 "Bahamas":       dict(top=0,  abroad=0,  note="no personal income tax."),
 "Norway":        dict(top=47.4, abroad=37.8, note="dividends ~37.8%; wealth tax ~1% on net assets."),
 "Sweden":        dict(top=52, abroad=30, note="30% on capital income; expert relief for some workers."),
 "Ireland":       dict(top=52, abroad=0,  note="40% + USC + PRSI. Non-domiciled residents pay nothing on foreign income kept abroad (remittance basis)."),
 "Slovenia":      dict(top=50, abroad=25, note="25% on capital income."),
 "Bulgaria":      dict(top=10, abroad=10, note="10% flat; dividends 5%."),
 "Albania":       dict(top=23, abroad=15, note="rough: 23% top; capital income ~15%."),
 "Morocco":       dict(top=37, abroad=37, note="worldwide; foreign pensions brought in get a large allowance."),
 "Colombia":      dict(top=39, abroad=39, note="worldwide for residents; wealth tax on big fortunes."),
 "Dominican Republic":dict(top=25, abroad=25, note="foreign investment income only taxed from your 3rd year of residence."),
 "Germany":       dict(top=47.5, abroad=26.4, note="45% + solidarity surcharge; 25% + soli on capital income."),
 "Andorra":       dict(top=10, abroad=10, note="10% maximum; 'passive residence' needs 90 days/yr and investment."),
 "United Kingdom":dict(top=48, abroad=48, note="Scotland 48% top rate; new arrivals: foreign income and gains exempt for the first 4 years (FIG regime)."),
}

# When you become tax-resident. days = days per year that make you resident (for
# tests that average over several years, the per-year figure if you come every year).
# home = what having a home there (house/flat you can stay in; bare land usually
# doesn't count) does: kind "hard" = resident above home.days; "soft" = may make you
# resident depending on your ties; "opt" = lets you CHOOSE residency (useful if low tax).
RES = {
 "Japan":        dict(days=365, note="resident only if your domicile is in Japan or you've lived there a year; 90-day visa-free visits stay non-resident."),
 "Canada":       dict(days=183, home=dict(kind="soft", days=0, note="a home in Canada is a significant residential tie: with weak ties elsewhere CRA can treat you as resident (worldwide income taxed) even under 183 days. A vacation home with strong ties abroad usually stays non-resident, but it's a real risk."), note="183 days (sojourner rule) or residential ties."),
 "USA":          dict(days=122, note="183-day test weighted over 3 years: coming every year, 122+ days/yr makes you resident (121 is safe). Closer-connection exception (Form 8840) can protect you up to 182 days. ESTA visitors max 90 days per visit; longer needs a B-2 visa."),
 "Austria":      dict(days=183, home=dict(kind="hard", days=70, note="any home you can use makes you resident. Second-home rule: if your centre of life has been abroad 5+ yrs, using the Austrian home on no more than 70 days a year keeps you non-resident (keep a day log).")),
 "Portugal":     dict(days=183, home=dict(kind="soft", days=0, note="a home kept as your habitual residence can make you resident under 183 days.")),
 "Malaysia":     dict(days=182, note="182 days, or shorter stays linked to longer ones across years."),
 "Thailand":     dict(days=180, note="180 days in a calendar year."),
 "Chile":        dict(days=183, note="183 days in any 12 months (or across 2 consecutive years)."),
 "Poland":       dict(days=183, home=dict(kind="soft", days=0, note="centre of vital interests in Poland makes you resident.")),
 "Romania":      dict(days=183, home=dict(kind="soft", days=0, note="centre of vital interests in Romania makes you resident.")),
 "Brazil":       dict(days=183, note="183 days in 12 months; a permanent visa makes you resident from day one."),
 "Indonesia":    dict(days=183, note="183 days in 12 months."),
 "New Zealand":  dict(days=183, home=dict(kind="soft", days=0, note="a 'permanent place of abode' in NZ makes you resident whatever the days. IRD (IS 25/16): a holiday home used 2-3 months a year isn't one by itself, but ownership counts toward your ties and courts have found ownership alone enough. Investor-visa home buyers are being told to get a binding ruling."), note="183 days in any 12 months, or a permanent place of abode."),
 "Argentina":    dict(days=365, note="resident after 12 months or with permanent residency."),
 "Turkey":       dict(days=183, home=dict(kind="soft", days=0, note="settling (domicile) in Turkey makes you resident.")),
 "Switzerland":  dict(days=90, home=dict(kind="soft", days=0, note="domicile with intent to stay makes you resident; a holiday home alone usually doesn't."), note="90 days without work (30 days if working)."),
 "Fiji":         dict(days=183, home=dict(kind="soft", days=0, note="domicile in Fiji (your permanent home) makes you resident."), note="183 days in any 12 months, or domicile."),
 "Georgia":      dict(days=183, note="183 days in any 12 months."),
 "New Caledonia":dict(days=183, home=dict(kind="soft", days=0, note="your 'foyer' (main home) there makes you resident.")),
 "Vanuatu":      dict(days=183, note="no income tax either way."),
 "Grenada":      dict(days=183, note="183 days."),
 "Australia":    dict(days=183, home=dict(kind="soft", days=0, note="a permanent place of abode in Australia makes you resident.")),
 "France":       dict(days=183, home=dict(kind="soft", days=0, note="your 'foyer' (main home/family) or main work in France makes you resident; a holiday home alone doesn't.")),
 "United Kingdom":dict(days=183, home=dict(kind="hard", days=120, note="Statutory Residence Test: a home available to you plus 90+ days the year before = 2 ties, so returning visitors become resident from 121 days.")),
 "South Africa": dict(days=183, home=dict(kind="soft", days=0, note="'ordinarily resident' if SA is your real home."), note="physical-presence test: 91+ days every year for 6 years and 915+ in the last 5 (so ~183/yr if you come every year)."),
 "Italy":        dict(days=183, home=dict(kind="soft", days=0, note="your habitual abode or centre of interests in Italy makes you resident."), note="183 days, counting part days."),
 "Spain":        dict(days=183, home=dict(kind="soft", days=0, note="centre of economic interests or family in Spain makes you resident.")),
 "Greece":       dict(days=183, home=dict(kind="soft", days=0, note="permanent home/centre of vital interests in Greece makes you resident.")),
 "Croatia":      dict(days=183, home=dict(kind="soft", days=0, note="owning or renting a home you use (domicile) can make you resident.")),
 "Montenegro":   dict(days=183, note="183 days."),
 "Cyprus":       dict(days=183, home=dict(kind="opt", days=60, note="60-day rule: with a Cyprus home, a local job/company and no other tax residence you can choose to be resident after 60 days (then non-dom: 0% on dividends).")),
 "Malta":        dict(days=183, home=dict(kind="soft", days=0, note="intention to live in Malta makes you resident.")),
 "UAE":          dict(days=183, home=dict(kind="opt", days=90, note="90 days + a permanent home + UAE residence visa or job gets you a UAE tax-residence certificate.")),
 "Panama":       dict(days=183, note="183 days."),
 "Costa Rica":   dict(days=183, note="183 days."),
 "Mexico":       dict(days=183, home=dict(kind="soft", days=0, note="setting up your home (casa habitación) in Mexico makes you resident; with homes in two countries your centre of vital interests decides."), note="no fixed day count; 183 is a rule of thumb."),
 "Uruguay":      dict(days=183, home=dict(kind="opt", days=60, note="buy property worth ~US$430k+ and stay 60 days: you can become tax-resident (and use the 11-year holiday).")),
 "Philippines":  dict(days=180, note="180 days."),
 "Vietnam":      dict(days=183, home=dict(kind="soft", days=0, note="a registered residence or a rented home on a 183+ day lease makes you resident.")),
 "Sri Lanka":    dict(days=183, note="183 days."),
 "Mauritius":    dict(days=90, note="183 days in a year OR 270 over 3 years: coming every year, 90+ days/yr makes you resident."),
 "Bahamas":      dict(days=183, note="no income tax either way."),
 "Norway":       dict(days=90, note="183 days in 12 months OR 270 in 36: coming every year, 90+ days/yr makes you resident."),
 "Sweden":       dict(days=183, home=dict(kind="soft", days=0, note="keeping an 'essential connection' (e.g. a home) to Sweden can keep you resident.")),
 "Ireland":      dict(days=140, note="183 days in a year OR 280 over 2 years: coming every year, 140+ days/yr makes you resident."),
 "Slovenia":     dict(days=183, home=dict(kind="soft", days=0, note="habitual residence / centre of interests in Slovenia makes you resident.")),
 "Bulgaria":     dict(days=183, note="183 days in 12 months."),
 "Albania":      dict(days=183, home=dict(kind="soft", days=0, note="a permanent home in Albania can make you resident.")),
 "Morocco":      dict(days=183, home=dict(kind="soft", days=0, note="your 'foyer' in Morocco makes you resident.")),
 "Colombia":     dict(days=183, note="183 days in any 365."),
 "Dominican Republic":dict(days=183, note="183 days."),
 "Germany":      dict(days=183, home=dict(kind="hard", days=0, note="any home you keep and use (owned or rented) makes you resident even for short stays; a tax treaty may still assign you to your home country.")),
 "Andorra":      dict(days=183, note="183 days; passive residence needs 90 days a year."),
}

# Countries without listings in the app yet: weather sample points (sea / ski areas).
EXTRA = {
 "Italy": [(46.54, 12.14), (45.98, 9.26), (40.63, 14.48)],
 "Spain": [(39.6, 2.9), (36.51, -4.88), (42.70, 0.93)],
 "Greece": [(35.51, 24.02), (39.62, 19.92), (37.45, 25.33)],
 "Croatia": [(43.51, 16.44), (42.65, 18.09), (45.08, 13.64)],
 "Montenegro": [(42.42, 18.77), (42.29, 18.84)],
 "Cyprus": [(34.68, 33.04), (34.77, 32.42)],
 "Malta": [(35.90, 14.51), (36.05, 14.25)],
 "UAE": [(25.20, 55.27), (25.79, 55.94)],
 "Panama": [(8.78, -82.44), (7.53, -80.03), (9.34, -82.24)],
 "Costa Rica": [(9.98, -85.65), (10.30, -85.84), (10.46, -84.70)],
 "Mexico": [(20.21, -87.46), (20.91, -100.74), (23.45, -110.22)],
 "Uruguay": [(-34.96, -54.94), (-34.84, -54.63)],
 "Philippines": [(11.18, 119.39), (9.85, 126.05)],
 "Vietnam": [(16.05, 108.22), (10.22, 103.96)],
 "Sri Lanka": [(6.03, 80.22), (5.95, 80.45)],
 "Mauritius": [(-20.01, 57.58), (-20.33, 57.37)],
 "Bahamas": [(23.52, -75.82), (25.10, -76.15)],
 "Norway": [(68.20, 13.90), (60.86, 8.55)],
 "Sweden": [(63.40, 13.08), (57.64, 18.29)],
 "Ireland": [(51.55, -9.40), (53.45, -9.90)],
 "Slovenia": [(46.37, 14.11), (45.53, 13.57)],
 "Bulgaria": [(41.84, 23.49), (42.42, 27.70)],
 "Albania": [(39.87, 20.00), (40.10, 19.74)],
 "Morocco": [(31.51, -9.77), (30.54, -9.71)],
 "South Africa": [(-34.05, 18.40), (-34.05, 23.37)],
 "Colombia": [(10.40, -75.50), (11.24, -74.20)],
 "Dominican Republic": [(19.31, -69.54), (19.75, -70.41)],
 "Germany": [(47.49, 11.09), (54.90, 8.31)],
 "Andorra": [(42.58, 1.67), (42.51, 1.52)],
}

# rough FX to show band thresholds in US$ (labelled "≈" in the UI)
FX_USD = {"USD": 1, "CAD": 0.73, "GBP": 1.27, "EUR": 1.08, "JPY": 0.0064, "THB": 0.029, "MYR": 0.22,
          "AUD": 0.66, "NZD": 0.60, "CLP": 0.00105, "IDR": 0.000062, "PHP": 0.0175, "MXN": 0.054,
          "CRC": 0.0019, "PAB": 1, "GEL": 0.37, "RON": 0.217, "BGN": 0.55, "AED": 0.272, "UYU": 0.025,
          "FJD": 0.44, "ZAR": 0.056, "CHF": 1.13, "PLN": 0.25, "TRY": 0.029, "BRL": 0.18}
BANDS_PATH = os.path.join(ROOT, "scripts", "geo", "income_bands.json")

def hdi_table():
    p = os.path.join("/tmp", "hdr25.csv")
    if not os.path.exists(p):
        urllib.request.urlretrieve(HDR_URL, p)
    rows = list(csv.DictReader(open(p, encoding="latin-1")))
    return {r["country"]: float(r["hdi_2023"]) for r in rows if r.get("hdi_2023")}

def climate(lat, lon, cache, years=10):
    """Monthly normals. Open-Meteo bills long requests as many calls (~days/14 x vars/10),
    so points added later use 5 years and 4 variables to stay inside the hourly quota."""
    key = f"{lat:.2f},{lon:.2f}"
    if key in cache: return cache[key]
    if os.environ.get("NO_FETCH"): return None      # build from cached weather only
    daily = "temperature_2m_max,temperature_2m_min,precipitation_sum,sunshine_duration,snowfall_sum" if years == 10 \
        else "temperature_2m_max,precipitation_sum,sunshine_duration,snowfall_sum"
    url = ("https://archive-api.open-meteo.com/v1/archive?latitude=%.4f&longitude=%.4f"
           "&start_date=%d-01-01&end_date=2025-12-31&daily=%s&timezone=UTC") % (lat, lon, 2026 - years, daily)
    for attempt in range(8):
        try:
            d = json.load(urllib.request.urlopen(url, timeout=90))["daily"]; break
        except Exception as e:
            wait = 120 if "429" in str(e) else 10 * (attempt + 1)
            print("  retry", key, e, f"(waiting {wait}s)", file=sys.stderr); time.sleep(wait)
    else:
        return None
    d.setdefault("temperature_2m_min", [None] * len(d["time"]))
    m = defaultdict(lambda: dict(tmax=[], tmin=[], wet=[], sun=[], snow=[]))
    for i, t in enumerate(d["time"]):
        b = m[int(t[5:7])]
        v = lambda k: d[k][i]
        if v("temperature_2m_max") is None: continue
        b["tmax"].append(v("temperature_2m_max"))
        if v("temperature_2m_min") is not None: b["tmin"].append(v("temperature_2m_min"))
        b["wet"].append(1 if (v("precipitation_sum") or 0) >= 1 else 0)
        b["sun"].append((v("sunshine_duration") or 0) / 3600)
        b["snow"].append(1 if (v("snowfall_sum") or 0) >= 1 else 0)
    out = []
    for mo in range(1, 13):
        b = m[mo]; f = lambda k: round(statistics.mean(b[k]), 2) if b[k] else None
        out.append({k: v for k, v in dict(tmax=f("tmax"), tmin=f("tmin"), wet=round(f("wet") * 30, 1), sun=f("sun"), snow=round(f("snow") * 30, 1)).items() if v is not None})
    cache[key] = out
    json.dump(cache, open(CACHE, "w"))
    time.sleep(4)
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
        # special land: oceanfront (≤1 km from the sea, or tagged beach/waterfront) and ski (≤2 km from a lift)
        def price_set(sub, min_band=10):
            band_ = [r["usd"] / r["ac"] for r in sub if 0.25 <= r["ac"] <= 50]
            vals, skew_ = (band_, False) if len(band_) >= min_band else ([r["usd"] / r["ac"] for r in sub], True)
            if len(vals) < 3: return None
            q = statistics.quantiles(vals, n=4) if len(vals) >= 4 else [None, None, None]
            return {"usd": round(statistics.median(vals)), "p25": q[0] and round(q[0]), "p75": q[2] and round(q[2]),
                    "n": len(vals), "skew": skew_,
                    "basis": "plots of 0.25-50 acres" if not skew_ else "all such plots (few, or mostly small: rough)"}
        is_ocean = lambda r: (r.get("coast_km") is not None and r["coast_km"] <= 1) or r.get("v") in ("beachfront", "waterfront")
        is_ski = lambda r: r.get("ski_km") is not None and r["ski_km"] <= 2
        price_sets = {"ocean": price_set([r for r in allland if is_ocean(r)]),
                      "ski": price_set([r for r in allland if is_ski(r)]),
                      "either": price_set([r for r in allland if is_ocean(r) or is_ski(r)])}
        pts = sorted([r for r in rows if r.get("lat") is not None and r.get("lon") is not None], key=lambda r: r["lat"])
        samples = []
        for q in (0.2, 0.5, 0.8):
            if pts:
                r = pts[min(len(pts) - 1, int(q * len(pts)))]
                if not any(abs(r["lat"] - a) < 0.05 and abs(r["lon"] - b) < 0.05 for a, b in samples):
                    samples.append((round(r["lat"], 3), round(r["lon"], 3)))
        print(f"{cf}: {len(rows)} rows, {len(land)} $/acre, climate at {samples}", file=sys.stderr)
        clim = [c for c in (climate(a, b, cache, years=10 if f"{a:.2f},{b:.2f}" in cache else 5) for a, b in samples) if c]
        months = [{k: round(statistics.mean(c[i][k] for c in clim), 2) for k in ("tmax", "wet", "sun", "snow")} for i in range(12)] if clim else None
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
            "price_sets": price_sets,
            "hdi": h, "hdi_note": hnote,
            "tax": dict(t, total10=round(t["purchase"] + t["foreign"] + 10 * t["annual"], 1)),
            "income_tax": INCOME[cf], "residency": RES[cf],
            "climate_points": samples, "months": months,
        }
    for cf, pts in EXTRA.items():
        if cf in out["countries"] or cf in hidden: continue
        print(f"{cf}: no listings, climate at {pts}", file=sys.stderr)
        clim = [c for c in (climate(a, b, cache, years=5) for a, b in pts) if c]
        months = [{k: round(statistics.mean(c[i][k] for c in clim), 2) for k in ("tmax", "wet", "sun", "snow")} for i in range(12)] if clim else None
        t = TAX[cf]
        out["countries"][cf] = {
            "n": len(by.get(cf, [])), "n_price": 0, "price_basis": "no land listings in the app yet", "price_skew": True,
            "usd_per_acre": None, "usd_per_acre_p25": None, "usd_per_acre_p75": None,
            "hdi": hdi.get(HDR_NAME.get(cf, cf)), "hdi_note": None,
            "tax": dict(t, total10=round(t["purchase"] + t["foreign"] + 10 * t["annual"], 1)),
            "income_tax": INCOME[cf], "residency": RES[cf],
            "climate_points": pts, "months": months,
        }
    bands = json.load(open(BANDS_PATH)) if os.path.exists(BANDS_PATH) else {}
    for cf, c in out["countries"].items():
        b = bands.get(cf)
        if b:
            c["bands"] = dict(b, usd_per_unit=FX_USD.get(b.get("currency")))
    json.dump(out, open(os.path.join(ROOT, "docs", "countries.json"), "w"), ensure_ascii=False, indent=1)
    print("wrote docs/countries.json:", len(out["countries"]), "countries", file=sys.stderr)

if __name__ == "__main__":
    main()
