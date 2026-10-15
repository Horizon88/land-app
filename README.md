# Land App

A personal land and home hunting app for special places: ski-in/ski-out, sea and lake
frontage, real views. It pulls listings from 20+ countries, throws out the ordinary and
the legally broken, and surfaces the few worth a look.

**Open it:** https://horizon88.github.io/land-app/

It's a single static page (`docs/index.html`): no build step, no server. Everything it
shows comes from JSON files in `docs/`, refreshed by the Python scripts in `scripts/`.

## Using it

| | |
|---|---|
| **✨ Gems** (opens here) | A top-300 feed across every country. A listing only qualifies if it is strong on at least two of: value (price vs similar listings nearby), setting (water, ski lift, view, station), motivated seller, real size. Each row says why. |
| **🎯 Hunts** | One-click definitions of special: 🌅 Best views, 🎿 Japan ski homes / ski land, 🌊 Japan by the sea, ♨️ Onsen, 🗼 Tokyo value flats, ⛷ Austria ski-in/out, 🏞 Austria lakeside, 🏛 Vienna below-district. Deal-killers are hidden. |
| **🃏 Triage** | The top 20 untriaged listings of whatever you're viewing, one at a time: **K** keep (★ shortlist), **S** skip (archive), **M** maybe (👁 watchlist). Gems and hunts learn from it. |
| **Region tabs** | 🏠 Massachusetts, 🗼 Tokyo, 🏛 Vienna: land and homes for one area in one view. |
| **🚫 Hide countries** | Remove whole countries everywhere. Defaults for every device live in `docs/prefs.json`. |
| **Detail panel** | Photos, ⛔ deal-killers, ⚠ warnings, ✓ perks, zoning / tenure / road facts, sea & lake distance, Claude's photo review, bid guidance, offers, packages. |
| **Archive / star** | Saved per browser, synced via ☁ Sync, and made permanent in `docs/archived.json` (use **📋 Copy archive list**). |

## Coverage

37.6k listings in the app (the ordinary rest is archived in `data/raw/`):

| Country | In app | Main sources |
|---|---:|---|
| Japan | 11,775 | SUUMO: land + used houses (all 47 prefectures, sea / ski only), Tokyo apartments, abandoned ski resorts |
| Canada | 5,097 | REW, LandQuest, mountain/ski sweeps |
| USA | 3,874 | Redfin (South Coast MA land + homes), LandSearch |
| Austria | 3,245 | willhaben: lake / ski land + chalets, Vienna apartments; JamesEdition alpine |
| Portugal, Malaysia, Thailand, Chile, Poland, Romania, Brazil, Indonesia, NZ, Argentina, Turkey, Switzerland, Fiji, Georgia, New Caledonia, Vanuatu, Grenada, Australia | 13.6k | imovirtual, mudah.my, FazWaz / DotProperty / PropertyHub / thailand-property, Portal Inmobiliario, OLX, chavesnamao, realtor.com/international … |

## How listings get filtered

1. **Scrape** list pages per source (`scripts/*_scrape.py`), then **merge** into `docs/listings.json` (`*_merge.py`).
2. **Geo enrichment** (`scripts/geo_enrich.py`): real distance to the sea (Japan) and to lakes (Austria), from Natural Earth plus hand-drawn lake axes.
3. **Quality gate** (`scripts/quality_gate.py`): Japan and Austria listings stay only if they're near the sea, a ski lift or a lake (or are Tokyo / Vienna apartments). Everything else goes to `data/raw/*.json.gz`.
4. **Detail checks** (`scripts/detail_enrich.py`): for the candidates that pass, the listing's own page is read for deal-killers (leasehold, unbuildable zone, farmland, can't-rebuild, no road, Grünland, Baurecht), warnings and perks (onsen rights, sea / Fuji / lake views, ski-in), plus photos. Cached in `data/detail_cache.json`.
5. **Clean** (`scripts/clean_listings.py`): sanity checks, value flags, stable plot codes (e.g. `TH-HV81KH`), local units (rai, ฿/rai).
6. **View score** (`scripts/viewshed.py`): from free terrain elevation (AWS Terrain Tiles), cast 72 rays 7 km out from each candidate and measure how much open sea or lake is actually visible, plus how near it is and whether the plot sits above its surroundings. That combines with view words in the listing and photo reviews into a 0–100 `view_score`. View leads the Gems ranking, and an outstanding view (≥80) qualifies on its own. **🌅 Best views** hunt; sort by view.
7. **Photo review**: Claude looks at finalists' photos and writes verdicts into `docs/reviews.json` (👍 lifts a listing in Gems, 👎 removes it).

Approximate locations are flagged: listings pinned to a town centre (common on willhaben)
can't claim ski-in/out or lakeside from distance alone.

## Refreshing

```bash
bash scripts/hourly_refresh.sh       # Thai sources: scrape, merge, score, clean; pushes only real new listings
bash scripts/deadlink_sweep.sh 2500  # re-check listing URLs, drop expired ones
# Japan / Austria
python3 scripts/suumo_japan_scrape.py land,house,apartment && python3 scripts/suumo_japan_merge.py
python3 scripts/willhaben_scrape.py && python3 scripts/willhaben_merge.py
python3 scripts/geo_enrich.py apply && python3 scripts/quality_gate.py \
  && python3 scripts/detail_enrich.py && python3 scripts/clean_listings.py
```

Scrapers that hit bot-protected sites go through a small Cloudflare Worker relay
(`cloudflare-worker.js`, deployed with `wrangler.toml`).

## Repo layout

| Path | What |
|---|---|
| `docs/` | The app (`index.html`) and its data: `listings.json`, `archived.json`, `reviews.json`, `prefs.json`, `saved_plots.json`, plans |
| `scripts/` | Scrapers, merges, enrichment, gate, cleaner, refresh jobs; `scripts/geo/` coastline + lake point sets |
| `data/` | Raw archives, detail-page cache, history |
| `browser_ext/` | Chrome extension to capture listings from Facebook groups, BAM and Thailand's DOL map |
| `.github/workflows/` | Scheduled refresh workflows |
| `cloudflare-worker.js` | The scraping relay |

`docs/AI_HANDOFF.md` is the briefing for another AI picking this up (data model,
scoring, legal rules, open threads). `HANDOVER.md` holds older notes.

Moved here from `Horizon88/hello`, which keeps the full earlier history.
