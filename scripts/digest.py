"""Daily digest: what's new and what got cheaper, per hunt.

Runs after snapshot_history.py. For each hunt (the same definitions as the app's
hunt chips), lists listings first seen since the last digest and listings whose
asking price was cut since then. Deal-killers and listings you skipped/archived
are left out. Writes docs/digest.md (the latest digest, also linked in the app)
and, when GITHUB_TOKEN / GITHUB_REPOSITORY are set (GitHub Actions), opens a
GitHub issue with it so it lands in your inbox.

State: data/digest_state.json remembers the last digest date.

Usage: python3 scripts/digest.py [--since YYYY-MM-DD] [--no-issue]
"""
import json, os, re, sys, urllib.request
from datetime import date, timedelta

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIST = os.path.join(ROOT, "docs", "listings.json")
STATE = os.path.join(ROOT, "data", "digest_state.json")
OUT = os.path.join(ROOT, "docs", "digest.md")
APP = "https://raw.githack.com/Horizon88/land-app/main/docs/index.html"
TOP = 8

def le(v, x): return v is not None and v <= x

SOUTHCOAST = re.compile(r"/MA/(?:north-|south-)?(?:westport|dartmouth|new-bedford|fairhaven|acushnet|mattapoisett|marion|rochester|"
                        r"(?:east-)?wareham|onset|fall-river|swansea|somerset|(?:east-)?freetown)/|-(?:westport|dartmouth|new-bedford|"
                        r"fairhaven|acushnet|mattapoisett|marion|rochester|wareham|fall-river|swansea|somerset|freetown)-ma-", re.I)

def state_of(r):
    if r.get("state"): return r["state"]
    m = re.search(r"[- ](AK|MT)$", r.get("rg") or "")
    return m.group(1) if m else None

def home_scale(r):
    return r.get("tp") != "house" or ((r.get("living_m2") or r.get("m2") or 0) <= 600 and (r.get("beds") or 0) <= 10)

# key, label, match, sort key (higher first)
HUNTS = [
    ("southcoast", "⚓ SouthCoast MA water view",
     lambda r: bool(SOUTHCOAST.search(r.get("u") or "")) and (r.get("v") in ("sea_visible", "waterfront") or (r.get("view_score") or 0) >= 40),
     lambda r: r.get("view_score") or 0),
    ("us_homes", "🇺🇸 USA ocean & ski homes",
     lambda r: r.get("cf") == "USA" and r.get("tp") == "house" and home_scale(r) and (le(r.get("coast_km"), 0.3) or le(r.get("ski_km"), 3)),
     lambda r: r.get("r") or 0),
    ("ak_mt", "🏔 Alaska & Montana",
     lambda r: state_of(r) in ("AK", "MT") and r.get("tp") != "apartment" and
               ((r.get("ac") or 0) >= 5 or le(r.get("coast_km"), 0.3) or (r.get("view_score") or 0) >= 40 or le(r.get("ski_km"), 3)),
     lambda r: (r.get("view_score") or 0) + (r.get("r") or 0)),
    ("ak_state", "🏛 Alaska state land", lambda r: "src:ak-dnr" in (r.get("rb") or ""), lambda r: r.get("view_score") or 0),
    ("jp_ski_home", "🎿 Japan ski homes",
     lambda r: r.get("cf") == "Japan" and r.get("tp") == "house" and home_scale(r) and le(r.get("ski_km"), 5)
               and (not r.get("year_built") or r["year_built"] >= 1981),
     lambda r: r.get("r") or 0),
    ("jp_ski_land", "🎿 Japan ski land",
     lambda r: r.get("cf") == "Japan" and (r.get("tp") or "land") == "land" and le(r.get("ski_km"), 3), lambda r: r.get("r") or 0),
    ("jp_sea", "🌊 Japan by the sea",
     lambda r: r.get("cf") == "Japan" and r.get("tp") not in ("apartment", "abandoned_ski") and
               (le(r.get("coast_km"), 1) or any(re.search(r"sea view|Fuji", p) for p in r.get("perks") or [])),
     lambda r: r.get("view_score") or 0),
    ("central_america", "🌊💧 Central America 2 of 3",
     lambda r: len(r.get("ca_signals") or []) >= 2, lambda r: len(r["ca_signals"]) * 100 + (r.get("view_score") or 0)),
    ("best_view", "🌅 Best views (anywhere)", lambda r: (r.get("view_score") or 0) >= 60, lambda r: r.get("view_score") or 0),
]

def money(r):
    usd = r.get("usd")
    return f"${usd:,.0f}" if usd else "?"

def size(r):
    if r.get("tp") == "house":
        bits = []
        if r.get("beds"): bits.append(f"{r['beds']}bd")
        if r.get("living_m2"): bits.append(f"{r['living_m2']:,} m²")
        if r.get("ac"): bits.append(f"{r['ac']:g} ac lot")
        return " · ".join(bits)
    return f"{r['ac']:g} ac" if r.get("ac") else ""

def line(r, cut=None):
    where = ", ".join(x for x in (r.get("a"), r.get("rg"), r.get("cf")) if x)
    extra = []
    if r.get("view_score"): extra.append(f"view {r['view_score']}")
    if r.get("coast_km") is not None and r["coast_km"] <= 1: extra.append(f"{r['coast_km'] * 1000:.0f} m to sea")
    if r.get("ski_km") is not None and r["ski_km"] <= 5: extra.append(f"{r['ski_km']:.1f} km to lift")
    if (r.get("days_on_market") or 0) >= 180: extra.append(f"{r['days_on_market']} days listed")
    price = money(r)
    if cut: price = f"~~${cut['from']:,.0f}~~ → **${cut['to']:,.0f}** (−{cut['pct']}%)"
    code = r.get("code", "")
    return (f"- [`{code}`]({APP}#{code}) {where} — {price} · {size(r)}"
            + (f" · {' · '.join(extra)}" if extra else "") + f" · [listing]({r['u']})")

def skipped_urls():
    out = set()
    p = os.path.join(ROOT, "docs", "decisions.json")
    if os.path.exists(p): out |= set((json.load(open(p)).get("skip") or {}).keys())
    p = os.path.join(ROOT, "docs", "archived.json")
    if os.path.exists(p):
        a = json.load(open(p))
        out |= set(a.keys() if isinstance(a, dict) else [x.get("u") for x in a if isinstance(x, dict)])
    return out

def build(since, today):
    d = json.load(open(LIST))
    skip = skipped_urls()
    live = [r for r in d if r.get("u") not in skip and not r.get("deal")]
    new = {r["u"] for r in live if (r.get("first_seen") or "") > since}
    cuts = {r["u"]: r["price_drops"][-1] for r in live if r.get("price_drops") and r["price_drops"][-1]["date"] > since}
    md = [f"# Land digest {today}", "",
          f"Changes since {since}: **{len(new):,} new listings**, **{len(cuts):,} price cuts** across all sources. "
          f"Below: the ones that match your hunts (top {TOP} each). Open the app → 🆕 / 📉 chips for everything: {APP}", ""]
    hits = 0
    for key, label, match, sk in HUNTS:
        rows = [r for r in live if match(r)]
        n_new = sorted([r for r in rows if r["u"] in new], key=sk, reverse=True)
        n_cut = sorted([r for r in rows if r["u"] in cuts], key=lambda r: -cuts[r["u"]]["pct"])
        if not n_new and not n_cut: continue
        hits += len(n_new) + len(n_cut)
        md.append(f"## {label}: {len(n_new)} new, {len(n_cut)} cut")
        if n_cut:
            md.append("**📉 Price cuts**")
            md += [line(r, cuts[r["u"]]) for r in n_cut[:TOP]]
        if n_new:
            md.append("**🆕 New**")
            md += [line(r) for r in n_new[:TOP]]
            if len(n_new) > TOP: md.append(f"- …and {len(n_new) - TOP} more")
        md.append("")
    if not hits: md.append("Nothing new or cheaper in your hunts today.")
    return "\n".join(md), hits, len(new), len(cuts)

def post_issue(title, body):
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo: return None
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/issues", method="POST",
                                 data=json.dumps({"title": title, "body": body[:65000], "labels": ["digest"]}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "User-Agent": "land-app-digest"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read()).get("number")

def main():
    args = sys.argv[1:]
    today = date.today().isoformat()
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    since = args[args.index("--since") + 1] if "--since" in args else st.get("last", (date.today() - timedelta(days=1)).isoformat())
    md, hits, n_new, n_cut = build(since, today)
    open(OUT, "w").write(md + "\n")
    print(f"digest {since} → {today}: {n_new} new, {n_cut} cuts overall; {hits} in hunts -> {OUT}", file=sys.stderr)
    if hits and "--no-issue" not in args:
        num = post_issue(f"Land digest {today}: {hits} new or cheaper in your hunts", md)
        if num: print(f"opened issue #{num}", file=sys.stderr)
    json.dump({"last": today}, open(STATE, "w"))

if __name__ == "__main__":
    main()
