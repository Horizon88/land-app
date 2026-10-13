# Handover — coastal land + ski-mountain + regulatory-watch app

If you're a fresh Claude session opened against `horizon88/landsearchprivate`, **read this first**.
It's a compressed summary of what's built, what's blocked, and the next moves.

## What the app is

Single-page land-hunting UI hosted from `docs/index.html` (currently raw.githack-served
from `horizon88/hello`, will move to Vercel once the new repo is wired). Aggregates
~23,000 land listings + ~700 condos/penthouses across BC, rest of Canada, Thailand,
Japan, New Zealand, Malaysia, Turkey. Layered scoring with a sortable + filterable
table, a Leaflet map, an archive/shortlist system, regulatory-watch panel.

## Data shape

`docs/listings.json` — one big array of compact rows. Key fields:

| Field | Meaning |
|---|---|
| `tp` | `land` / `apartment` / `penthouse` / `abandoned_ski` |
| `cf` | country flag — `Thailand` / `British Columbia` / `Canada` / `Japan` / `New Zealand` / `Malaysia` / `Turkey` / `USA` (planned) |
| `rg` | region/state |
| `a` | area/district within region |
| `r` | composite rating 0-300+ (size-dominant + bonuses) |
| `rb` | rating breakdown — `+`-separated tags like `acc+16+size+44+sea+12+ski-in+15` |
| `ac` / `m2` | acres / square meters |
| `usd` | price in USD; `lp` is raw original, `cur` is original currency |
| `lat` / `lon` | coords (some Japan rows are prefecture-centroid; see geocoding section) |
| `v` | view tag (`sea_visible` / `beachfront` / `inland` / `mountain` / `city/sky` / `river`) |
| `view_verified` | True/False/None; coastline + elevation gate |
| `ski_km` / `ski_r` | distance to nearest curated resort, name |
| `terrace_zone` | which of {Terrance, Smithers, Kitimat, Prince Rupert, Hazelton, Stewart} the BC listing is near |
| `foreign_friction` / `foreign_note` | per-jurisdiction non-resident-buyer penalty |
| `distress` / `distress_breakdown` | Thai land 0-100 composite + parts |
| `img` / `imgs[]` | photo URLs (gallery if multiple) |

## Scoring pipeline (run in order, idempotent)

```
ski_enrich.py           ski_km + ski-in/+15, ≤2km/+10, ≤10km/+5, rope-tow+8, sled+8
terrace_zone.py         BC northwest +5/+10/+15 by distance
foreign_friction.py     country friction (TR=-5, TH=-25, NZ=-10, etc.)
phuket_rerank.py        Phuket-specific layer (view-verified gate, zone)
thai_title_layer.py     Chanote +12, Nor Sor 3 -10
rescore_land.py         canonical size-dominant rescore — TIER, run LAST
turkey_merge.py         compacts TR scrape, applies own ski + foreign layers
thai_distress_merge.py  Thai distress signals → 🔥 index
merge_and_build.py      filters < 0.1 ac land, writes docs/listings.json + index.html
```

## Sources & scrapers (in `scripts/` + `/tmp/`)

| Source | Stage | Yield |
|---|---|---|
| REW.ca | direct curl | ~400 BC vacant land |
| Realtor.ca | stealth Playwright (Imperva-warmed) | 2,854 BC + 19,974 rest-of-Canada |
| FazWaz Thailand sea-view | direct curl | 760 verified sea-view Thai land |
| at-home Japan (suumo) | direct curl | 6,358 JP listings (city-geocoded) |
| realestate.co.nz JSON API | direct | 555 NZ rural |
| iProperty MY | direct | 40 MY |
| BAM (Thai bank NPL) | direct | 52 distressed BKK condos |
| Emlakjet TR | **ScraperAPI render=true** | 250 TR mountain-province land (10 of 15 provinces; 5 hit rate-limit) |
| Wikipedia 廃止スキー場 | direct + Wikipedia coords API | 345 closed JP ski resorts |

## Fetch fallback chain (`scripts/fetch.py`)

```
1. direct curl        free
2. Wayback Machine    free; stale by hours-days
3. residential proxy  HTTPS_PROXY_RESI env (IPRoyal pay-as-you-go)
4. ScraperAPI         SCRAPER_API_KEY env (auto-render + premium=true on protected)
```

`force="scraperapi"` jumps straight to stage 4 for known-Next.js targets where
direct returns a hollow shell (Emlakjet, Zillow, Redfin, Realtor.com).

## Secrets to add to the new repo

Settings → Secrets and variables → Actions → New repository secret:

| Name | Value | Notes |
|---|---|---|
| `HTTPS_PROXY_RESI` | `http://USER:PASS@geo.iproyal.com:12321` | IPRoyal pay-as-you-go; verified working (exit IP 201.94.149.121). Port 12321 is **blocked from Claude Code sandbox** but works fine from GHA runners. |
| `SCRAPER_API_KEY` | the ScraperAPI key | Free tier; rejects `premium=true` so LED court auctions remain blocked. Upgrade to Hobby ($49/mo) unlocks them. |

User's actual values are in `/home/user/land-app/.env` of the previous session (gitignored). Ask the user to paste them again or copy from there.

## Regulatory watch (`data/regulatory_watch.json` + `scripts/watch_regulatory.py`)

9 items currently tracked. Status from last run (2026-06-29):

| Item | Status | Notes |
|---|---|---|
| Conservation Amendment Bill (NZ) | blocked (Radware) | needs ScraperAPI premium |
| Foreign Buyer Ban (Canada) | ok | deadline 2027-01-01 (sunsets) — surfaces amber on chip |
| BC Speculation & Vacancy Tax | ok | |
| BC Short-Term Rental Act | ok | |
| OIA (NZ) | ok | |
| RMA reform (NZ) | ok | |
| Underused Housing Tax (Canada) | blocked (503) | intermittent canada.ca availability |
| Vacant Houses Act 空家対策 (Japan) | ok | |
| Forest Law 6831 amendments (TR) | ok | |
| Thai nominee crackdown 2026 | changed | catches new Bangkok Post articles by ID diff |

Weekly cron at 09:00 UTC Monday via `.github/workflows/weekly-scan.yml`. Re-runs the
watch + writes diffs back to `data/`.

## What's blocked from this sandbox

Recorded so the next session doesn't re-discover them:

- **Port 12321 outbound** — IPRoyal won't connect from Claude Code sandbox. Works
  from GHA runners. Run all IPRoyal-dependent scrapes via GHA.
- **LED court auctions** (`led.go.th/asset/`) — requires ScraperAPI premium
  (~$49/mo) or IPRoyal. The genuine Thai forced-sale gold mine; worth unblocking.
- **Sahibinden, Hurriyet Emlak, Zingat** — Cloudflare. ScraperAPI basic gets only
  partial results. IPRoyal residential should work; test via GHA.
- **Realtor.com, Zillow, Redfin** — Akamai/PerimeterX. Need ScraperAPI premium or
  Bright Data Web Unlocker.
- **GitHub MCP + git proxy scoped to ONE repo per session** — sessions can't
  push to a different repo than they were spawned for. This is the gating
  constraint behind the entire dual-repo move.

## Active TODO when this session resumes

1. **Run `proxy-smoke-test.yml`** in the new repo. Confirm IPRoyal exit IP appears
   in logs + per-target reachability.
2. **Production scrape workflows via GHA**:
   - `tr-scrape-fortnightly.yml` — retries 5 failed TR provinces + paginates pp 2-4 of 10 working
   - `usa-scrape-monthly.yml` — LandWatch Aspen/Park City/Jackson/Big Sky/Tahoe/Stowe
   - `led-auctions-weekly.yml` — gated on IPRoyal or ScraperAPI premium
3. **Distress Index v2** when ≥2 weekly price snapshots exist in `data/price_history.json`
4. **USA in UI** — chip + color + foreign_friction layer (USA: 0 baked-in; light
   restrictions on agricultural land in some states)
5. **Vercel deploy URL** — once user finishes the Vercel integration the URL
   replaces every raw.githack reference in docs/instructions

## Where to look in the tree

```
docs/index.html              UI (lazy-loads listings.json + regulatory_watch.json)
docs/listings.json           ~23k listings (5 MB)
docs/regulatory_watch.json   front-end copy of the watch registry
data/regulatory_watch.json   canonical registry; watch_regulatory.py writes here
data/seen.json               weekly-scan dedup (existing listings the cron has seen)
scripts/scan.py              the weekly fresh-listings scraper
scripts/notify.py            opens GitHub issues for newly-discovered high-rated
scripts/score.py             scoring functions used by scan.py
scripts/watch_regulatory.py  the watch poller
scripts/fetch.py             unified direct→wayback→proxy→scraperapi
.github/workflows/weekly-scan.yml      Monday-09:00-UTC cron
.github/workflows/proxy-smoke-test.yml manual-dispatch IPRoyal verifier
vercel.json                  static-serve docs/, 5-min CDN cache on listings.json
```

## Open user feedback signals

- Mobile-first; never use bold-link markdown (`**`) in chat replies (user disliked)
- Rating must be size-dominant; sub-acre lots heavily penalized (already enforced)
- Spelling: "Terrance" not "Terrace" (per user explicit preference, in code + UI)
- "lets do this" / "make a list and build it" pattern — prefers proposals + immediate execution, not multi-step confirmation loops
- Frustration when too many manual steps assigned — do max work autonomously, only ask when the action genuinely requires the user's account access (secrets, repo creation, OAuth)
