# Land App: improvement plan (Oct 2026)

**Goal.** The app should answer two questions:

1. Which countries and seasons work for us, on tax, visas, weather and cost?
2. Which specific oceanfront, ski or great-view properties are worth flying to see?

Everything else is secondary.

## Where things stand (measured 23 Oct 2026)

| Fact | Why it matters |
|---|---|
| 37,622 listings, but only **9,562 (25%)** are oceanfront (≤1 km from the sea) or ski (≤2 km from a lift). Only 2,212 are within 300 m of the sea, and 766 within 500 m of a lift | Most of what the app loads is land you don't want |
| 7,328 are city apartments (Tokyo, Vienna) | No longer a goal |
| 14,233 have no photo; 1,674 are pinned to a town centre | Hard to judge; view and distance figures are unreliable for these |
| Last refresh 12 Oct; scheduled jobs paused | Prices and availability are going stale |
| The app downloads a 34 MB file on every visit, and each data commit adds ~34 MB to git | Slow on a phone; the repo will bloat |
| No permanent link (GitHub Pages isn't on), so every update means a new link | Friction |
| Top-ranked lifestyle countries (Italy, Spain, Greece, Croatia, Cyprus, Malta) have **no listings** | They can't be compared on price |
| Tax model covers each country alone: no home-country tax, and no combining seasons across countries | Can't answer "can we split the year without becoming resident anywhere?" |
| Bugs this month (NaN scores, CSS clash, a broken coastline) were caught by eye | Needs an automatic check |

## Phase 1: solid foundation (about 1 session, no input needed)

1. **Permanent link**: you enable GitHub Pages (Settings → Pages → `main`, `/docs`).
2. **Ship only what matters**: keep oceanfront, ski, strong-view and your picks (~9.6k rows), split by country, and load each country on demand. That's roughly 5× faster on a phone. The rest stays in `data/raw`.
3. **Stop git bloat**: move data snapshots out of the main history (release assets or a data branch).
4. **Smoke test before every push**: a headless check that the app and ranking page load with no errors and key numbers are sane.
5. **View scores** for the roughly 1k plots newly recognised as coastal after the distance fix.

## Phase 2: "Can we actually own it?" (1 session, needs both passports)

- A per-listing ownership badge, based on your passport and your wife's:
  - Thai, Philippine and Indonesian land is closed to foreigners, but may be open to a spouse holding that nationality.
  - NZ homes are banned for most foreigners (Active Investor Plus exception: NZ$5M+).
  - Canada bans foreigners from buying urban homes until 2027.
  - Mexico's coastal zone requires a bank trust (fideicomiso).
  - Switzerland caps sales to foreigners (Lex Koller).
  - Malta and Cyprus require permits for non-EU buyers.
- Gems and hunts hide or flag listings you can't legally buy.

## Phase 3: year planner (about 2 sessions), the main decision tool

- Build a year from legs, e.g. Dec–Mar Hakuba, May–Jun Portugal, Jul–Aug Croatia. The planner checks each leg against:
  - Visa limits for both passports, including Schengen's 90-in-180 rule across all its countries.
  - Tax residency in each country (days and home rules).
  - **Your home country's rules**: some keep taxing you until you prove residence elsewhere, and some have exit taxes.
  - Weather by month.
- Output: a safe / watch / danger rating per leg, and a yearly tax bill.
- Compare strategies: "resident nowhere new" vs. "become resident in a low-tax place" (Cyprus 60-day rule, Malta, UAE, Georgia, Malaysia, Panama, Uruguay).

## Phase 4: fill the gaps where it counts (2–3 sessions)

Target the countries the planner ranks highest. My first guesses:

- **Coast**:
  - Italy (Immobiliare: Sardinia, Liguria, Amalfi)
  - Spain (Idealista: Mallorca, Costa Brava)
  - Greece (Spitogatos: Crete, Ionian)
  - Croatia (Njuškalo: Istria, Dalmatia)
  - Cyprus, Portugal's coast (Idealista.pt)
- **Ski**:
  - US ski towns via Redfin (Utah, Colorado, Idaho, Montana, Vermont)
  - BC's Kootenays and Okanagan (REW)
  - Italian Dolomites, Andorra
  - Hakuba, Niseko and Myoko (SUUMO, already covered)
- **Fix existing listings**: photos for those without, exact coordinates where portals provide them.
- **Refresh**: one weekly refresh of these special-land sources only. This needs your OK, since you paused the jobs.

## Phase 5: true cost per listing (1 session)

- Total cost of ownership:
  - price
  - purchase and foreign-buyer taxes
  - annual property tax
  - typical upkeep and insurance
  - FX
- Build cost for land (local cost per m² for a modest house), so land and finished homes compare fairly.
- Rank by **cost per week you'd actually use it**, not just $/acre.

## Phase 6: decide and act (ongoing)

- **Link drop-box**: send an Instagram or listing link, and it's automatically identified, added to Your picks, and put on price watch.
- **Weekly digest**: new gems, price cuts, delistings.
- **Shared shortlist with your wife**: both vote. A trip planner groups the finalists by region.
- **Due-diligence checklist per country**: title, zoning, foreign-buyer consent, tax clearance, local lawyer. Also a terrain view panorama and photo review for finalists.

## Throughout: accuracy and trust

- Every tax, visa and residency rule carries a source and a "verified on" date. A monthly check flags stale ones.
- Where two countries could both claim you, the panel shows which one the tax treaty favours.

## Decisions needed

1. Which EU country are you tax-resident in now, and will you keep a home there?
2. Your wife's passport(s).
3. Budget, and land-to-build vs. finished home.
4. OK to enable GitHub Pages and one weekly refresh?
5. First regions to fill. Suggested: Sardinia, Mallorca, Croatia's coast, the Dolomites and US ski towns.

**Order:** 1 → 2 → 3 → 4 → 5 → 6. The decision tools come before more scraping, because the planner shows which countries deserve new data sources.
