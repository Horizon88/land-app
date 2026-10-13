"""Merge nominee-scan results into listings.json.

Adds to flagged Thai rows:
  nominee:  {n, e, hits, own, excerpt?}   evidence bundle
  leverage: 0-100                          n + e, capped

n >= 20 is the flag threshold. 'company-only-transfer' (the FazWaz
structured Land Ownership field offering ONLY a company/share route) is the
strongest single signal that the land sits in a foreigner-controlled Thai
company — a legally-exposed structure whose seller cannot hold out.
"""
import json, sys
from collections import Counter

scan = json.load(open("/tmp/nominee_scan.json"))
d = json.load(open("/home/user/land-app/docs/listings.json"))

def title_quality(deed, own):
    """Classify what's actually being sold. The leverage thesis needs a
    FREEHOLD title held in a company — a leasehold has no trapped land to
    force a transfer of, so it's excluded from the hunt.
    Returns (quality, freehold) where quality ∈
      chanote | ns3g | ns3 | lease | other."""
    dl = (deed or "").lower()
    opts = {o.strip().lower() for o in (own or "").split(",") if o.strip()}
    lease_only = bool(opts) and opts <= {"leasehold"}
    if "lease" in dl or lease_only:
        return "lease", False
    if "chanote" in dl or "nor sor 4" in dl or "chanod" in dl:
        return "chanote", True
    if "3 gor" in dl or "3g" in dl or "3 kor" in dl or "sor 3 gor" in dl:
        return "ns3g", True
    if "nor sor 3" in dl or "ns3" in dl or "sor 3" in dl:
        return "ns3", True
    # no deed stated: freehold iff a Thai/company route is offered
    freehold = ("company" in opts) or ("thai ownership" in opts)
    return "other", freehold

# idempotency: clear previous nominee fields
for r in d:
    r.pop("nominee", None)
    r.pop("leverage", None)

flagged = lever = leaseskip = 0
for r in d:
    rec = scan.get(r.get("u") or "")
    if not rec or not rec.get("ok") or rec.get("n", 0) < 20:
        continue
    quality, freehold = title_quality(rec.get("deed", ""), rec.get("own", ""))
    if quality == "lease":
        # leasehold — no freehold title to squeeze; not a leverage play
        leaseskip += 1
        continue
    nom = {"n": rec["n"], "e": rec.get("e", 0), "hits": rec.get("hits", []),
           "own": rec.get("own", "")}
    if rec.get("excerpt"):
        nom["excerpt"] = rec["excerpt"][:300]
    # enrichment: deed quality, staleness, recent-bump
    stale = 0
    dom = rec.get("dom")
    if dom:
        nom["dom"] = dom
        nom["listed"] = rec.get("listed", "")
        if dom > 730: stale = 20
        elif dom > 365: stale = 10
        upd = (rec.get("updated") or "").lower()
        if stale and any(k in upd for k in ("day", "week")):
            stale += 5  # stale listing the seller is still actively bumping
            nom["hits"] = nom["hits"] + ["stale-but-bumping"]
    if rec.get("updated"):
        nom["updated"] = rec["updated"]
    deed = rec.get("deed", "")
    nom["deed"] = deed
    nom["title_q"] = quality
    nom["freehold"] = freehold
    title_bonus = 0
    if quality == "chanote":
        title_bonus = 5   # clean, fully-transferable freehold title
    elif quality in ("ns3g", "ns3"):
        title_bonus = 2   # transferable but weaker — only worth it if the land is special
    # a leasehold route offered ALONGSIDE company means share-transfer isn't the
    # ONLY exit — demote the company-only signal the scanner may have scored
    lease_offered = "leasehold" in {o.strip().lower() for o in (rec.get("own","")).split(",")}
    base = rec["n"]
    if lease_offered and "company-only-transfer" in nom["hits"]:
        nom["hits"] = ["company-or-lease-transfer" if h == "company-only-transfer" else h for h in nom["hits"]]
        base = max(0, base - 25)
    r["nominee"] = nom
    r["leverage"] = min(100, base + rec.get("e", 0) + stale + title_bonus)
    flagged += 1
    if rec.get("e", 0) >= 15 or stale >= 15:
        lever += 1

json.dump(d, open("/home/user/land-app/docs/listings.json", "w"), separators=(",", ":"))
print(f"flagged {flagged} nominee rows ({lever} with active exit pressure; {leaseskip} leaseholds excluded)", file=sys.stderr)
tq = Counter(r["nominee"]["title_q"] for r in d if r.get("nominee"))
print("title quality:", tq.most_common(), file=sys.stderr)
hits = Counter(h for r in d if r.get("nominee") for h in r["nominee"]["hits"])
print("signal counts:", hits.most_common(), file=sys.stderr)
rg = Counter(r["rg"] for r in d if r.get("nominee"))
print("by region:", rg.most_common(10), file=sys.stderr)
