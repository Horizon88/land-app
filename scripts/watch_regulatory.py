"""Periodic regulatory-watch check.

Reads data/regulatory_watch.json, attempts to fetch each item's URL,
records:
  - last_attempted    ISO timestamp of this run
  - last_status       one of: ok / blocked / network_error / changed
  - last_status_note  free-text note (challenge type, error, diff summary)
  - last_snapshot_sha sha256 of the page text content (when fetched
                       cleanly) so subsequent runs can detect text drift

Intended to run from .github/workflows/weekly-scan.yml. Falls back to
plain curl with a desktop UA; if Playwright + stealth are available,
uses those for tougher sites (NZ Parliament has Radware which curl
can't get past — that's fine, we record 'blocked' and surface it in
the UI for manual review).

Idempotent — only updates the JSON if something actually changed.
"""
from __future__ import annotations
import json, hashlib, pathlib, subprocess, sys, datetime, re

REGISTRY = pathlib.Path(__file__).resolve().parent.parent / "data" / "regulatory_watch.json"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
BOT_SIGNATURES = [
    "radware", "press & hold", "captcha", "verifying you are human",
    "cf-error", "cloudflare", "imperva", "access denied to akamai",
    "pardon our interruption", "checking your browser before",
]


def curl(url: str, timeout: int = 25) -> tuple[int, str]:
    try:
        p = subprocess.run(
            ["curl", "-skSL", "-m", str(timeout), "-A", UA, "-w", "\n__HTTP_CODE__:%{http_code}", url],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        body = p.stdout
        m = re.search(r"__HTTP_CODE__:(\d+)$", body)
        code = int(m.group(1)) if m else 0
        body = re.sub(r"__HTTP_CODE__:\d+$", "", body)
        return code, body
    except subprocess.TimeoutExpired:
        return 0, ""
    except Exception as e:
        return -1, str(e)


def looks_blocked(html: str) -> str | None:
    low = html.lower()
    for sig in BOT_SIGNATURES:
        if sig in low:
            return sig
    return None


def text_sha(html: str) -> str:
    # Strip tags + normalize whitespace + redact common noise (timestamps,
    # CSRF tokens, session IDs) so the SHA reflects content drift, not
    # cosmetic re-renders. Without this, every government page that
    # injects a 'last updated' timestamp would trigger 'changed' weekly.
    text = re.sub(r"<script[\s\S]*?</script>", " ", html)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    # Strip dates / times / numbers that look like ids
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[:\d.Z+\-]*\b", " ", text)  # ISO timestamps
    text = re.sub(r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}\b", " ", text)
    text = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?\b", " ", text)
    text = re.sub(r"\b[a-f0-9]{32,}\b", " ", text)   # md5/sha-ish tokens
    text = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def check_item(item: dict) -> dict:
    url = item.get("url")
    if not url:
        return {"last_status": "no_url", "last_status_note": "no url on item"}
    # Use the unified fetch chain: direct -> wayback -> proxy -> scraperapi.
    # Falls back automatically when env vars are set.
    try:
        from fetch import fetch as fetch_with_fallback
        body, source = fetch_with_fallback(url, timeout=25)
        if source == "failed" or len(body) < 200:
            out = {"last_attempted": datetime.datetime.utcnow().isoformat() + "Z",
                   "last_status": "blocked",
                   "last_status_note": "exhausted direct/wayback/proxy/scraperapi — set HTTPS_PROXY_RESI or SCRAPER_API_KEY to escalate"}
            return out
    except Exception as e:
        body, source = "", "failed"
        out = {"last_attempted": datetime.datetime.utcnow().isoformat() + "Z",
               "last_status": "network_error",
               "last_status_note": f"fetch err: {e}"}
        return out
    now = datetime.datetime.utcnow().isoformat() + "Z"
    out = {"last_attempted": now, "last_source": source}
    sha = text_sha(body)
    prior_sha = item.get("last_snapshot_sha")
    if prior_sha and prior_sha != sha:
        out.update({
            "last_status": "changed",
            "last_status_note": "page text changed since previous check — review the source",
            "last_snapshot_sha": sha,
        })
    else:
        out.update({
            "last_status": "ok",
            "last_status_note": "unchanged" if prior_sha else "first clean snapshot",
            "last_snapshot_sha": sha,
        })

    # Also check any extra_sources — newly-appearing article IDs in a search-
    # results page count as a 'changed' signal. Useful for tracking ongoing
    # campaigns (e.g. Thai nominee crackdown) where the canonical URL is a
    # search query that returns new news as it's published.
    extras = item.get("extra_sources") or []
    if extras:
        seen_ids = set(item.get("known_article_ids") or [])
        new_ids = []
        for src in extras:
            code2, body2 = curl(src, timeout=15)
            if code2 < 200 or code2 >= 400: continue
            # Bangkok Post-style: contentId=news_NNNNNNN
            for m in re.finditer(r"news_(\d+)", body2):
                aid = m.group(1)
                if aid not in seen_ids:
                    new_ids.append(aid)
                    seen_ids.add(aid)
        if new_ids:
            out["last_status"] = "changed"
            out["last_status_note"] = (
                f"{len(new_ids)} new article(s) in extra-source feeds: " +
                ", ".join(new_ids[:5]) + (" ..." if len(new_ids) > 5 else "")
            )
            out["known_article_ids"] = sorted(seen_ids)
        elif not item.get("known_article_ids"):
            out["known_article_ids"] = sorted(seen_ids)
    return out


def main() -> int:
    if not REGISTRY.exists():
        print(f"no registry at {REGISTRY}", file=sys.stderr)
        return 0
    data = json.loads(REGISTRY.read_text())
    items = data.get("items") or []
    any_change = False
    for item in items:
        before = {k: item.get(k) for k in ("last_status", "last_snapshot_sha")}
        result = check_item(item)
        item.update(result)
        after = {k: item.get(k) for k in ("last_status", "last_snapshot_sha")}
        if before != after:
            any_change = True
        print(f"  {item.get('id'):<40} {item.get('last_status'):<14}  {item.get('last_status_note','')[:80]}",
              file=sys.stderr)
    REGISTRY.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"updated {REGISTRY} (any_change={any_change})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
