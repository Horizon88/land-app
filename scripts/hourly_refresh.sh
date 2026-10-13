#!/usr/bin/env bash
# Hourly (or any-cadence) Thai-inventory refresh.
# Runs the full scrape -> merge -> nominee -> clean pipeline and pushes ONLY
# when genuinely new listings appeared, so frequent runs don't spam the repo
# with empty churn commits. Safe to run repeatedly.
#
# Usage:  bash scripts/hourly_refresh.sh
# Exit 0 always (a scraper hiccup must not wedge the cron); logs to stderr.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 0
# the Python scripts use /home/user/land-app; point it at this clone if needed
[ -e /home/user/land-app ] || ln -s "$(pwd -P)" /home/user/land-app 2>/dev/null || true
BRANCH="main"

log(){ echo "[$(date -u +%H:%M:%S)] $*" >&2; }

# make sure we're on the working branch and current
git fetch origin "$BRANCH" -q 2>/dev/null || true
git checkout -B "$BRANCH" "origin/$BRANCH" -q 2>/dev/null || git checkout "$BRANCH" -q 2>/dev/null || true

# snapshot current URL set so we can measure genuine net-new
python3 - <<'PY'
import json
d=json.load(open('docs/listings.json'))
json.dump([r.get('u') for r in d], open('/tmp/pre_refresh_urls.json','w'))
print('snapshot', len(d))
PY

# fresh fetch (clear caches so it's not a replay)
rm -f /tmp/dotproperty.json /tmp/fazwaz_south.json /tmp/propertyhub_th.json /tmp/thailandproperty.json

log "scraping DotProperty…";        timeout 900 python3 scripts/dotproperty_scrape.py       2>>/tmp/hr.log || log "dotproperty partial"
log "scraping FazWaz South…";       timeout 900 python3 scripts/fazwaz_south_th_scrape.py    2>>/tmp/hr.log || log "fazwaz partial"
log "scraping PropertyHub…";        timeout 900 python3 scripts/propertyhub_th_scrape.py     2>>/tmp/hr.log || log "propertyhub partial"
log "scraping thailand-property…";  timeout 900 python3 scripts/thailandproperty_scrape.py   2>>/tmp/hr.log || log "thailand-property partial"

log "merging…"
python3 scripts/fazwaz_south_th_merge.py  2>>/tmp/hr.log || true
python3 scripts/propertyhub_th_merge.py   2>>/tmp/hr.log || true
python3 scripts/dotproperty_merge.py      2>>/tmp/hr.log || true
python3 scripts/thailandproperty_merge.py 2>>/tmp/hr.log || true

log "nominee scan/merge…"
python3 scripts/nominee_scan.py  2>>/tmp/hr.log || true
python3 scripts/nominee_merge.py 2>>/tmp/hr.log || true

log "clean/value pass…"
python3 scripts/clean_listings.py 2>>/tmp/hr.log || true

# measure genuine net-new Thai listings vs snapshot.
# EXCLUDE src:dotproperty — its merge replaces the whole source each run and
# DotProperty's pagination is non-deterministic, so it churns URLs every run
# and would otherwise fool the gate into committing noise hourly. Only count
# net-new from the stable-URL sources (fazwaz / propertyhub / thailand-property).
NEW=$(python3 - <<'PY'
import json
d=json.load(open('docs/listings.json'))
pre=set(json.load(open('/tmp/pre_refresh_urls.json')))
new=[r for r in d if r.get('cf')=='Thailand'
     and r.get('u') not in pre
     and 'src:dotproperty' not in (r.get('rb','') or '')]
print(len(new))
PY
)
log "net-new Thai listings this run (excl. dotproperty churn): $NEW"

# commit + push ONLY if there is a real change AND net-new listings
if [ "${NEW:-0}" -gt 0 ] && ! git diff --quiet -- docs/; then
  git add docs/
  git commit -q -m "Hourly refresh: +$NEW new Thai listings

Automated scrape/merge/clean pass (DotProperty + FazWaz South + PropertyHub).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  for i in 1 2 3 4; do
    git push -u origin "$BRANCH" -q && { log "pushed (+$NEW)"; break; }
    sleep $((2**i))
  done
else
  # no net-new listings — discard any incidental churn so the tree stays clean
  git checkout -- docs/ 2>/dev/null || true
  log "no net-new listings — no commit"
fi
exit 0
