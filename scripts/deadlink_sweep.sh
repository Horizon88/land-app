#!/usr/bin/env bash
# Daily dead-link sweep across all sources. Runs the rotating checker and
# commits+pushes ONLY if it actually pruned dead listings. Safe to run
# repeatedly; the checker's own cache rotates coverage so each run checks a
# different slice.
#
# Usage:  bash scripts/deadlink_sweep.sh [CAP]
set -uo pipefail
cd "$(dirname "$0")/.." || exit 0
# the Python scripts use /home/user/land-app; point it at this clone if needed
[ -e /home/user/land-app ] || ln -s "$(pwd -P)" /home/user/land-app 2>/dev/null || true
BRANCH="main"
CAP="${1:-1500}"
log(){ echo "[$(date -u +%H:%M:%S)] $*" >&2; }

git fetch origin "$BRANCH" -q 2>/dev/null || true
git checkout -B "$BRANCH" "origin/$BRANCH" -q 2>/dev/null || git checkout "$BRANCH" -q 2>/dev/null || true

before=$(python3 -c "import json;print(len(json.load(open('docs/listings.json'))))")
log "sweeping up to $CAP rows for dead links…"
OUT=$(python3 scripts/deadlink_check.py "$CAP" 2>&1); echo "$OUT" >&2
after=$(python3 -c "import json;print(len(json.load(open('docs/listings.json'))))")
pruned=$(( before - after ))
log "pruned $pruned dead listings ($before -> $after)"

if [ "$pruned" -gt 0 ] && ! git diff --quiet -- docs/listings.json; then
  git add docs/listings.json
  git commit -q -m "Dead-link sweep: pruned $pruned expired listings

Automated across SUUMO + Thai portals (removed only definitive 404 /
delisted-marker rows; network failures never prune).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
  for i in 1 2 3 4; do git push -u origin "$BRANCH" -q && { log "pushed (-$pruned)"; break; }; sleep $((2**i)); done
else
  git checkout -- docs/ 2>/dev/null || true
  log "nothing pruned — no commit"
fi
exit 0
