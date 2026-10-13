"""Unified fetch helper with a four-stage fallback chain.

Every scraper that wants to be unblockable should import `fetch()` from here
instead of calling curl directly. The chain tries the cheapest option first
and only escalates when needed:

  1. Direct curl     — free, fastest. Works for ~40% of sites.
  2. Wayback Machine — free. Stale by hours-to-days, but defeats every
                        bot wall because we're hitting archive.org, not the
                        target. Good for press releases / regulator pages
                        that don't move fast.
  3. Residential proxy — costs bandwidth. Wired via HTTPS_PROXY_RESI env
                        var (e.g. IPRoyal: http://user:pass@gate.iproyal.com:12321).
                        Bypasses Cloudflare/Akamai bot walls when the
                        IP itself was the blocker.
  4. Scraping API    — costs per request. Wired via SCRAPER_API_KEY env
                        var (ScraperAPI by default, easy to swap for
                        Bright Data Web Unlocker / ScrapingBee). Handles
                        captchas + JS rendering. Last resort.

Env vars (drop any one in and the chain extends automatically):
  HTTPS_PROXY_RESI   residential proxy URL  (Stage 3)
  SCRAPER_API_KEY    ScraperAPI key         (Stage 4 — auto-render + captcha)
  SCRAPER_API_URL    override base URL      (default: http://api.scraperapi.com)

Returns (body, source_tag) where source_tag is one of:
  'direct' | 'wayback' | 'proxy' | 'scraperapi' | 'failed'
"""
from __future__ import annotations
import os, re, subprocess, urllib.parse

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
# Phrases that mean 'you are being blocked' — not just 'this site uses
# Cloudflare for CDN'. Earlier version matched too eagerly.
BOT_SIGS = [
    "radware captcha",
    "press & hold",
    "verifying you are human",
    "cf-error",
    "cf-chl-bypass",
    "imperva incapsula",
    "access denied to akamai",
    "pardon our interruption",
    "checking your browser before accessing",
    "just a moment...</title>",   # Cloudflare interstitial title, distinctive
    "datadome",
    "access denied</title>",
    "you have been blocked",
    "enable javascript and cookies to continue",
]


def _curl(url: str, timeout: int = 18, proxy: str | None = None) -> tuple[int, str]:
    cmd = ["curl", "-skSL", "--compressed", "-m", str(timeout), "-A", UA]
    if proxy:
        cmd += ["-x", proxy]
    cmd += ["-w", "\n__HTTP_CODE__:%{http_code}", url]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        body = p.stdout
        m = re.search(r"__HTTP_CODE__:(\d+)$", body)
        code = int(m.group(1)) if m else 0
        body = re.sub(r"__HTTP_CODE__:\d+$", "", body)
        return code, body
    except (subprocess.TimeoutExpired, Exception):
        return 0, ""


def _looks_blocked(html: str, code: int) -> bool:
    if code in (0, -1) or code >= 400:
        return True
    low = html.lower()[:8000]   # bot pages are always small + show banner early
    return any(s in low for s in BOT_SIGS)


def _try_relay(url: str, timeout: int) -> tuple[int, str]:
    """Cloudflare Worker relay — forwards through IPRoyal residential proxy.
    Set CF_RELAY_URL to the deployed worker, e.g.
      https://landrelay.yourname.workers.dev"""
    relay = os.environ.get("CF_RELAY_URL")
    if not relay: return 0, ""
    relay = relay.rstrip("/")
    api = f"{relay}/?url={urllib.parse.quote(url, safe='')}"
    return _curl(api, timeout=timeout)


def fetch(url: str, timeout: int = 18, allow_stale: bool = True,
          force: str | None = None) -> tuple[str, str]:
    """Return (body, source_tag). Empty body + 'failed' if every stage missed.

    allow_stale=False skips Wayback (use for live data like price scrapes
    where a day-old cache is misleading).

    force='scraperapi' jumps straight to JS-rendering ScraperAPI — use when
    the target is known to be Next.js / React / Angular with no
    server-rendered listing data (Emlakjet, Zillow, Redfin, Realtor.com).
    force='proxy' jumps straight to the residential proxy."""

    # force= jumps directly to a specific stage; useful for known
    # JS-rendered targets where 'direct' returns a hollow shell.
    if force == "relay":
        code, body = _try_relay(url, timeout=timeout + 10)
        if not _looks_blocked(body, code) and len(body) > 200:
            return body, "cf-relay"
        return body, "failed"
    if force == "scraperapi":
        key = os.environ.get("SCRAPER_API_KEY")
        if key:
            base = os.environ.get("SCRAPER_API_URL", "http://api.scraperapi.com")
            api = f"{base}/?api_key={key}&render=true&url={urllib.parse.quote(url, safe='')}"
            code, body = _curl(api, timeout=90)
            # ScraperAPI returns a small 'Request failed... premium=true' message
            # for protected domains; auto-escalate when we see it.
            if "premium=true" in body or "ultra_premium=true" in body or (len(body) < 400 and "Request failed" in body):
                api2 = api + "&premium=true"
                code, body = _curl(api2, timeout=120)
                if len(body) > 200 and not _looks_blocked(body, code):
                    return body, "scraperapi_premium"
            if len(body) > 200 and not _looks_blocked(body, code):
                return body, "scraperapi"
            return body, "failed"
    if force == "proxy":
        proxy = os.environ.get("HTTPS_PROXY_RESI")
        if proxy:
            code, body = _curl(url, timeout=timeout + 5, proxy=proxy)
            if len(body) > 200 and not _looks_blocked(body, code):
                return body, "proxy"
            return body, "failed"

    # Stage 1 — direct
    code, body = _curl(url, timeout=timeout)
    if not _looks_blocked(body, code) and len(body) > 200:
        return body, "direct"

    # Stage 2 — Wayback Machine
    if allow_stale:
        # Use the closest-to-now snapshot
        wb_api = f"https://archive.org/wayback/available?url={urllib.parse.quote(url, safe='')}"
        wb_code, wb_body = _curl(wb_api, timeout=15)
        if wb_code == 200 and '"available":true' in wb_body:
            m = re.search(r'"url":\s*"(https?://web\.archive\.org/[^"]+)"', wb_body)
            if m:
                snap_url = m.group(1).replace("\\/", "/")
                code, body = _curl(snap_url, timeout=timeout)
                if not _looks_blocked(body, code) and len(body) > 200:
                    return body, "wayback"

    # Stage 3a — Cloudflare Worker relay (the relay itself goes through
    # IPRoyal residential proxy — bypasses sandbox proxy-host block).
    code, body = _try_relay(url, timeout=timeout + 15)
    if code and not _looks_blocked(body, code) and len(body) > 200:
        return body, "cf-relay"

    # Stage 3b — direct residential proxy (only works when the caller's
    # network can reach proxy gateways; Claude sandbox can't).
    proxy = os.environ.get("HTTPS_PROXY_RESI")
    if proxy:
        code, body = _curl(url, timeout=timeout + 5, proxy=proxy)
        if not _looks_blocked(body, code) and len(body) > 200:
            return body, "proxy"

    # Stage 4 — ScraperAPI (or compatible). Two-step: basic first, then premium
    # on protected-domain rejection.
    key = os.environ.get("SCRAPER_API_KEY")
    if key:
        base = os.environ.get("SCRAPER_API_URL", "http://api.scraperapi.com")
        api = f"{base}/?api_key={key}&render=true&url={urllib.parse.quote(url, safe='')}"
        code, body = _curl(api, timeout=60)
        if "premium=true" in body or (len(body) < 400 and "Request failed" in body):
            api2 = api + "&premium=true"
            code, body = _curl(api2, timeout=120)
            if not _looks_blocked(body, code) and len(body) > 200:
                return body, "scraperapi_premium"
        if not _looks_blocked(body, code) and len(body) > 200:
            return body, "scraperapi"

    return body, "failed"


if __name__ == "__main__":
    import sys
    for u in sys.argv[1:] or ["https://www.sahibinden.com/arsa-satilik"]:
        body, src = fetch(u)
        print(f"{src:<11}  {len(body):>8}  {u}")
