"""Rating function for ocean-view land listings (0-100).

Calibrated for a Canadian citizen. Scores combine value ($/m^2),
country access, view, title security, plot size fit, and practical signals.

Optionally penalises listings that match patterns from data/archives.json
(user's archived listings with tags + reasons). If a country/region has
2+ listings archived with the same tag, listings in that region get a
penalty proportional to the tag count.
"""
from __future__ import annotations
import json, math, pathlib, re

ACCESS = {
    "British Columbia": 25,
    "Japan": 23,
    "Malaysia": 18,
    "Thailand": 14,
    "New Zealand": 5,
}

BUMI = re.compile(r"\b(bumi[-\s]?lot|tanah[-\s]?rizab|rizab[-\s]?melayu|malay[-\s]?reserve|reserved[-\s]?malay)\b", re.I)
NON_BUMI = re.compile(r"\b(non[-\s]?bumi)\b", re.I)


def _load_archive_patterns():
    """Returns {('Country','Region'): {tag: count}} or empty dict if no archives.json."""
    path = pathlib.Path(__file__).resolve().parent.parent / "data" / "archives.json"
    if not path.exists():
        return {}, set()
    try:
        d = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}, set()
    archives = d.get("archives", d) if isinstance(d, dict) else {}
    region_tags: dict[tuple[str, str], dict[str, int]] = {}
    archived_urls: set[str] = set()
    # We need country/region per URL; the archive only stores tags+reason.
    # The scanner caller passes country/region via the listing row; we match
    # by URL since the latest.csv is sibling of archives.json.
    latest = pathlib.Path(__file__).resolve().parent.parent / "data" / "latest.csv"
    if not latest.exists():
        return {}, set()
    import csv as _csv
    url_to_region: dict[str, tuple[str, str]] = {}
    with latest.open() as f:
        for r in _csv.DictReader(f):
            url_to_region[r.get("listing_link", "")] = (r.get("country", ""), r.get("region", ""))
    for url, entry in archives.items():
        archived_urls.add(url)
        key = url_to_region.get(url)
        if not key:
            continue
        for t in entry.get("tags", []):
            region_tags.setdefault(key, {})
            region_tags[key][t] = region_tags[key].get(t, 0) + 1
    return region_tags, archived_urls


_REGION_TAGS, _ARCHIVED_URLS = _load_archive_patterns()


def archive_penalty(country: str, region: str) -> tuple[int, list[str]]:
    """Return (penalty_points, reasons) for a (country, region) pair based on archives."""
    tags = _REGION_TAGS.get((country, region))
    if not tags:
        return 0, []
    # Sum tag counts that exceed the "sticky" threshold (>=2)
    sticky = {t: n for t, n in tags.items() if n >= 2}
    if not sticky:
        return 0, []
    # cap penalty at 20 points
    penalty = min(20, sum(min(n * 3, 12) for n in sticky.values()))
    reasons = [f"{t}×{n}" for t, n in sticky.items()]
    return penalty, reasons


def rate(row: dict) -> dict:
    """Mutates row in-place adding 'rating' and 'rating_breakdown'."""
    slug = (row.get("listing_link") or "").lower()
    country = row.get("country", "")

    # Pre-archived → drop way down; the user has explicitly rejected this URL.
    if row.get("listing_link") in _ARCHIVED_URLS:
        row["rating"] = 0.0
        row["rating_breakdown"] = "archived by user"
        return row

    access = ACCESS.get(country, 10)
    if country == "Malaysia" and BUMI.search(slug) and not NON_BUMI.search(slug):
        access = 0  # foreigner can't buy bumi/Malay-reserved

    try:
        upm2 = float(row["usd_per_m2"])
    except (KeyError, ValueError, TypeError):
        upm2 = 999.0
    value = 25.0 if upm2 <= 0.5 else max(0.0, 25.0 * (1 - math.log10(upm2 / 0.5) / 3))

    view = (row.get("view") or "").lower()
    view_pts = 20 if view == "beachfront" else (15 if view == "sea_visible" else (10 if view == "coastal" else 0))

    title = (row.get("title") or "").lower()
    if "chanote" in title or "freehold" in title:
        title_pts = 15
    elif "title deed" in title:
        title_pts = 10
    elif "nor sor" in title:
        title_pts = 8
    elif "lease" in title:
        title_pts = 5
    else:
        title_pts = 7
    if country == "Malaysia" and BUMI.search(slug):
        title_pts = 0

    try:
        acres = float(row.get("acres") or 0)
    except (ValueError, TypeError):
        acres = 0.0
    # Bigger is better (user prefers acreage, not building lots)
    if acres < 1:
        size_pts = 0
    elif acres < 5:
        size_pts = 4
    elif acres < 20:
        size_pts = 8
    elif acres < 100:
        size_pts = 14
    elif acres < 500:
        size_pts = 18
    else:
        size_pts = 20

    prac = 0
    try:
        if float(row.get("elev_m") or 0) > 20:
            prac += 3
    except (ValueError, TypeError):
        pass
    if any(k in slug for k in ("panoram", "sea-view", "sea_view", "ocean", "view")):
        prac += 2
    prac = min(prac, 5)

    # Apply user-archive learning penalty
    penalty, reasons = archive_penalty(country, row.get("region", ""))

    rating = round(access + value + view_pts + title_pts + size_pts + prac - penalty, 1)
    row["rating"] = max(0.0, rating)
    bd = f"acc{access}+val{value:.0f}+view{view_pts}+title{title_pts}+size{size_pts}+prac{prac}"
    if penalty:
        bd += f"-arch{penalty}({','.join(reasons)})"
    row["rating_breakdown"] = bd
    return row

