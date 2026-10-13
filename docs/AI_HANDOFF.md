# Land-Hunt Project — AI Handoff Brief

> **Purpose of this file.** Paste it (or link it) into another AI so it can pick up
> this project cold. It explains what the project is, where everything lives, how the
> app and data pipeline work, the current live target, and the rules that must not be
> broken. Everything below is current as of the last commit that touched this file.
> If numbers look stale, regenerate them (see **§6 Refresh**).

---

## 1. TL;DR

A single-page web app for hunting **undervalued land**, with a heavy focus on
**Thai land that is nominee-held and sold by/through foreigners** — the thesis being
that a legally-exposed, motivated (often foreign) seller gives a buyer leverage to
acquire well below ask. The app aggregates ~25k land listings across 20 countries
(Thailand is the priority), scores each for value / forced-sale distress / ownership
leverage, and provides deal-tracking, land-assembly ("package") math, and an
offer-approval workflow shared across devices.

The owner is a foreign (non-Thai) buyer. Anything involving Thai land ownership must
respect that a foreigner **cannot** hold Thai land in their own name (see **§9**).

## 2. Where everything lives

- **Repo:** `github.com/Horizon88/land-app` (moved here from `Horizon88/hello`, which keeps the old history)
- **Branch:** `main`
- **The app:** `docs/index.html` — one ~200 KB vanilla-JS file (Leaflet map +
  filterable table + localStorage workspaces). No build step, no framework.
- **The data:** `docs/listings.json` — the entire inventory, one flat JSON array.
- **Open the live app** (GitHub Pages / githack; commit-pin the URL to beat CDN cache):
  `https://horizon88.github.io/land-app/` (GitHub Pages, served from `docs/` on `main`)
- **There is no login.** It's a static page. The only "account" feature is a Firebase
  **☁ Sync** pairing (a code, not a password) so a second person (the owner's
  partner, "Siri") can approve offers and have them reach the owner across devices.

### Key files
| Path | What it is |
|---|---|
| `docs/index.html` | the whole app (UI, filters, scoring display, deal tracking, offer drafts) |
| `docs/listings.json` | full listing inventory (flat array; see §4) |
| `docs/saved_plots.json` | manually-saved DOL parcels incl. the live Khao Thong target |
| `docs/foreign_notes.json` | per-country foreign-ownership notes (sidecar) |
| `docs/plans/*.html` | standalone deliverables (site layouts, DD letter) |
| `scripts/*_scrape.py` / `*_merge.py` | per-source scraper → merge pipeline (§6) |
| `scripts/nominee_scan.py` / `nominee_merge.py` | Thai nominee/leverage scoring (§5) |
| `scripts/clean_listings.py` | data-quality + value-flag pass, run last (§6) |
| `browser_ext/` | MV3 extension to capture auth-walled sites (FB, BAM, DOL) |

## 3. The strategy (why the scores exist)

The owner wants **leverage against a forced seller**, not just a cheap price. Three
independent signals, each its own field and filter:

1. **Ownership leverage (Thai only).** Thai land held in a company where the *only*
   exit offered is a **share transfer** ("Company"-only ownership on FazWaz) is a
   strong signal the land is **nominee-structured** — technically illegal under the
   Land Code, so the seller is exposed and motivated. Scored in `leverage`.
2. **Forced-sale distress.** Keyword + age signals: "urgent / must sell / price
   reduced / relocation / divorce", plus long time-on-market. Scored in `distress`.
3. **Value.** Underpriced $/m² vs. its own region (bottom quartile). Boolean
   `distressed` (yes, badly named — see §8).

Title quality matters: **Chanote (Nor Sor 4 Jor)** freehold > NS3G > NS3 > leasehold.
Leaseholds are largely excluded from leverage (a 30+30+30 "90-year lease" is deemed
invalid by the Thai Supreme Court, so it's not a real asset).

## 4. Data model — `docs/listings.json`

One flat JSON array. Rows are terse (keys abbreviated to keep the payload small).
Common fields:

| key | meaning |
|---|---|
| `tp` | type, always `"land"` |
| `cf` | country (e.g. `"Thailand"`) |
| `rg` | region/province (⚠ spelling varies by source — `"Phangnga"` (DotProperty) vs `"Phang Nga"` (FazWaz) are the same province) |
| `a` | area/locality label |
| `ac` / `m2` | size in acres / square metres |
| `usd` | price in USD (converted; THB source ≈ /36) |
| `upm` | USD per m² (the value metric) |
| `cur` / `lp` | original currency + list price string |
| `v` | view (`sea_view`, `sea_visible`, `coastal`, …) |
| `t` | title type (`Chanote`, `NS3`, …) |
| `lat` / `lon` | coords (5-dp ≈ 1 m) |
| `r` | overall rating/score (sort default) |
| `rb` | score breakdown string, starts with `src:<source>` |
| `u` | source URL (unique key) |
| `imgs` | image URLs |
| `days_on_market` / `first_seen` | staleness |
| `distress` (int) / `distress_breakdown` | 🔥 forced-sale score + why |
| `distressed` (bool) | 💎 bottom-quartile-$/m² value flag (§8) |
| `leverage` (int) / `nominee` | 🎯 Thai ownership-leverage score + evidence |
| `t`, `th_title_bonus` | Thai title quality |
| `coast_km` / `ski_km` | distance to coast / ski lift |
| `price_is_official` | true for DOL parcels priced at treasury value (suppresses bid guidance) |
| `has_market_ask` / `xref_url` | a DOL parcel cross-referenced to a real market listing |

## 5. Scoring models (in the scripts + app)

- **`leverage`** (nominee_merge.py): `n` (nominee signal from FazWaz "Land Ownership"
  field — `Company`-only = +45) + `e` (exit-pressure keywords) + staleness bonus +
  title-quality bonus. 224 Thai rows currently flagged, ~63 with active exit pressure.
- **`distress`** (each merge script): keyword hits + time-on-market tiers. ≥30 = the
  🔥 "Forced-sale signals" filter. 205 Thai rows.
- **`distressed`** (clean_listings.py): true when `upm` is in the bottom quartile of a
  ≥8-comp same-country/region cohort. 876 Thai rows. The 💎 "Cheap for area" filter.
- **`fairValue(r)`** (in index.html): fair value = median $/m² of **size-similar AND
  view-matched** comps (sea-view compared only to sea-view, never blended with inland)
  × parcel size × title multiplier. Opening bid = fair − a discount widened by
  leverage / distress / staleness, capped below ask. This is the "what should I offer"
  engine shown in each listing's detail panel.

## 6. Refresh — how to pull new listings

Pipeline per Thai source is **scrape → merge**, then global **nominee scan → nominee
merge → clean**. All scrapers proxy through a Cloudflare Worker relay
(`https://landrelay.flag-theory.workers.dev/?url=<encoded>`; add `&render=1&wait=N`
for JS pages, but that burns a ~10 min/day browser-rendering budget — avoid unless
needed). From repo root:

```bash
# 1. clear caches for a genuine fresh fetch, snapshot current URLs to diff
rm -f /tmp/dotproperty.json /tmp/fazwaz_south.json /tmp/propertyhub_th.json
python3 -c "import json;d=json.load(open('docs/listings.json'));json.dump([r['u'] for r in d],open('/tmp/pre.json','w'))"

# 2. scrape (each takes a few min; can run in parallel)
python3 scripts/dotproperty_scrape.py       # 10 South-Thai provinces, list-page JSON-LD
python3 scripts/fazwaz_south_th_scrape.py    # coastal provinces, detail pages, distress
python3 scripts/propertyhub_th_scrape.py     # Thai-language portal

# 3. merge (order matters; dotproperty dedups against FazWaz syndication)
python3 scripts/fazwaz_south_th_merge.py
python3 scripts/propertyhub_th_merge.py
python3 scripts/dotproperty_merge.py

# 4. re-score Thai nominee/leverage (only scans new FazWaz pages; resumes from cache)
python3 scripts/nominee_scan.py && python3 scripts/nominee_merge.py

# 5. ALWAYS run last: data-quality + value-flag pass
python3 scripts/clean_listings.py

# 6. commit + push to the working branch
git add docs/ && git commit -m "Refresh Thai inventory" && git push origin main
```

**Interpreting the delta:** `dotproperty_merge.py` fully *replaces* its own source each
run, so its "new rows" count is inflated by re-churn — it is **not** all net-new market
inventory. The signals that actually matter are the **nominee** and **distress**
deltas and the FazWaz/PropertyHub new counts. Other scrapers exist for non-Thai
sources (Japan/Canada mountain, Chile, Argentina, Portugal, Poland, etc.).

## 7. Live target — Khao Thong ฿120M sea-view parcel (Krabi)

The one active acquisition. Saved in `docs/saved_plots.json`.

- **What:** ~23 rai hillside **sea-view** assembly of two adjoining Chanote deeds —
  **54240 (land no. 27, 21-3-4.5 rai)** + **50861 (land no. 26, ~1-3-6.3 rai)**,
  Khao Thong, Mueang Krabi. Map sheet 4725 III 7202-00. Coords ≈ 8.1706, 98.7507.
- **Ask:** ฿120M (≈ $3.33M, ≈ $88.5/m²) via **Pawinee Real Estate**, cross-referenced
  to a Facebook listing. Treasury value only ฿390/sqwa (understated for view land).
- **Site facts (owner-confirmed from Google Earth profiles):** slope ~**25%**
  (moderate — buildable, below the EEA/EIA steepness trigger), **road reaches** it
  from the **west** (access is mid-slope on the left, *not* the south), sea view over
  Phang Nga bay to the **south/downhill**, high ground to the **north**. Buildable
  across most of the ~145 m depth.
- **Fair-value read:** view-matched comps put fair ≈ **$139/m² ≈ ฿189M**, so the ฿120M
  ask is ~**63% of fair** — a genuine discount, not a stretch.
- **Bid state:** owner already bid **฿70.5M (฿3M/rai)** → **no reply** (an underbid).
  Standing advice: open **฿95–105M**, conditional on due diligence + survey.
- **Rental:** neighbour Airbnb villas (rooms/27970506 ≈ $500–750/night, near-full)
  prove the location books. Plan is one trophy villa @ ~$2,000/night (land/lifestyle
  play, ~2.5–3% yield) rather than a 23-villa development (EIA/capex/absorption risk).

### Deliverables already produced for this target
- **Site layouts** (3 schematic masterplans) → `docs/plans/khao-thong-site-layouts.html`
- **Lawyer DD instruction** (scoped to deeds 54240/27 + 50861/26 only) →
  `docs/plans/khao-thong-dd-request.html`
- **Surveyor RFQ** for 1 m contour survey (Thai, To: ThaiSurveyor, From: Siriprapa) —
  delivered inline in chat, not yet saved as a file.

## 8. Known issues / gotchas

- **Filter names were a trap (now fixed):** 💎 **"Cheap for area (value)"** = bottom-
  quartile $/m² (`distressed` bool); 🔥 **"Forced-sale signals"** = `distress` ≥ 30.
  They check *different* fields. The `distressed` bool was historically never set on
  any row, so 💎 matched nothing until clean_listings.py was fixed to compute it.
- **Province spelling varies by source** — `Phangnga`/`Phang Nga`, `Prachuap-khiri-khan`/
  `Prachuap Khiri Khan`, etc. Don't assume a single canonical string when filtering.
- **GitHub Actions is broken account-wide** (all scheduled runs fail at startup /
  billing). Don't rely on cron via Actions; refresh is manual or via a Claude Code
  Remote Routine.
- **Some PropertyHub bulk "southern" listings are actually central-Thailand
  industrial-estate land** (mislabelled by coords; the Thai title names give it away,
  e.g. Kabin Buri / Chachoengsao). Ignore those for a coastal-view hunt.
- **DotProperty syndicates FazWaz** — same plot, different URL; the merge dedups by
  coords+price, but expect churn in its row count.
- Lazudi and BAM (bank-repossession) are captcha/SPA-walled → use the browser
  extension capture flow, not the relay.

## 9. Rules that must not be broken

- **Do NOT use the owner's FazWaz credentials** (a login/password was leaked into an
  earlier transcript). Do not log into their account, and do not build **automated bulk
  seller messaging** — it's a ToS/PDPA/ban risk. Legitimate, individually-drafted offer
  letters are fine; spam is not.
- **Foreign ownership:** the buyer is not Thai and cannot hold Thai land personally.
  Any acquisition advice must be through a **compliant** structure (genuine
  non-nominee Thai company, registered long lease, BOI, or Thai-spouse) — never advise
  an illegal nominee arrangement, even though the app *hunts* sellers who used one.
- **Work on `main`** (or a feature branch merged into it).
- **Be frugal on GitHub** — don't open PRs unless asked; don't spam comments.

## 10. Standing open tasks (owner may pick any)

- Grade / view / title / fair-value read on the new distressed finds (e.g. the Phang
  Nga "urgent" palm plantation, though it's likely inland agricultural land).
- Draft the ฿95–105M serious offer (Thai + English) for the Khao Thong owner.
- Draw the access-road grade from the west to confirm entry gradient.
- Development pro-forma (single trophy villa vs. multi-villa) into the parcel detail.
- Fold DotProperty into a recurring refresh; add a dead-link checker.
- Save the surveyor RFQ into `docs/plans/` so it's linkable.

## 11. If you're the AI reading this

You can drive the whole project from the repo. To **refresh listings**, run §6. To
**work the live deal**, read `docs/saved_plots.json` and §7. To **change the app**,
edit `docs/index.html` (plain JS, no build). Always run `scripts/clean_listings.py`
before committing data, keep work on the one branch, and respect §9. When you finish a
change, commit + push and hand back the commit-pinned githack URL so the owner can open
the exact version.
