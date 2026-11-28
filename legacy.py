"""
Legacy Readiness and the validation record (Idea to Legacy, Nov 2026).

Legacy Readiness is the finish line every path (BUILD, FUND, SUSTAIN)
works toward: an organization that can run, raise money and make decisions
without its founder. Six markers, each met or not, with where the answer
came from:

    deputy        someone other than the ED could run it for three months
    decisions     key decisions, processes and passwords written down
    succession    a board-approved ED succession plan
    reserves      six or more months of operating reserves
    concentration no single funder above 30% of revenue
    candid        Candid Platinum Seal of Transparency

Reserves fill from the latest filed financials when not entered (flagged
as an estimate: net assets overstate true operating reserves). The Candid
marker fills from the org's recorded Seal. Everything else is entered by
Franklin from the evidence he checked.

The validation record answers "how do we know the scores mean something?":
  - self vs verified: for every client with both a free check-up score and
    a verified Diagnostic score, the average difference per area (how much
    leaders over- or under-rate themselves), and how often the check-up's
    gap matched the verified gap;
  - outcomes: events logged against a client (a grant won or lost, an
    expansion, a leadership transition) with the client's score at the
    time, so score bands can be compared with what actually happened.
"""

MARKERS = [
    {"key": "deputy", "name": "A deputy who could step in",
     "test": "Someone other than the executive director could run the organization for three months."},
    {"key": "decisions", "name": "Key decisions written down",
     "test": "Key decisions, processes and passwords are written down where others can find them."},
    {"key": "succession", "name": "Board-approved succession plan",
     "test": "The board has approved a succession plan for the executive director."},
    {"key": "reserves", "name": "Six months of reserves",
     "test": "At least six months of operating expenses held in reserve."},
    {"key": "concentration", "name": "No funder above 30% of revenue",
     "test": "No single funder provides more than 30% of revenue."},
    {"key": "candid", "name": "Candid Platinum Seal",
     "test": "The Candid profile holds the Platinum Seal of Transparency."},
]
MARKER_KEYS = {m["key"] for m in MARKERS}

# Grant results are logged in the existing funder outcomes table, not here.
OUTCOME_KINDS = {
    "expansion_opened": "Expansion opened",
    "expansion_paused": "Expansion paused or reversed",
    "transition_smooth": "Leadership transition held",
    "transition_rough": "Leadership transition disrupted",
    "other": "Other",
    # Logged by the system: closing an engagement, and the check-in a year later.
    "engagement_closed": "Engagement closed",
    "year_checkin": "One-year check-in",
}

# Check-up areas (self_scores keys) to InstitutionalOS dimension keys.
SELF_TO_DIM = {"strategy": "strategy", "program": "program", "revenue": "financial", "leadership": "leadership",
               "operations": "operations", "partnerships": "partnerships", "governance": "governance"}


def assess(inputs, snapshot=None, candid_seal=""):
    """inputs: {marker_key: True|False|None}. Returns met/total/items."""
    i = dict(inputs or {})
    items = []
    for m in MARKERS:
        k = m["key"]
        val, source, note = i.get(k), "entered", ""
        if val is None and k == "reserves" and snapshot and snapshot.get("total_expenses"):
            months = max(snapshot.get("net_assets") or 0, 0) / (snapshot["total_expenses"] / 12)
            val, source, note = months >= 6, "990 estimate", f"about {months:.1f} months from net assets on the latest 990"
        if val is None and k == "candid" and candid_seal:
            val, source = str(candid_seal).strip().lower() == "platinum", "Candid Seal on file"
            note = f"current Seal: {candid_seal}"
        items.append({"key": k, "name": m["name"], "test": m["test"],
                      "met": bool(val) if val is not None else None, "source": source if val is not None else "missing", "note": note})
    met = sum(1 for x in items if x["met"])
    known = sum(1 for x in items if x["met"] is not None)
    return {"met": met, "total": len(MARKERS), "known": known, "items": items,
            "missing": [x["name"] for x in items if x["met"] is None],
            "ready": met == len(MARKERS)}


def gap_rule(scores, stage, weights, gates):
    """One rule for the gap that will break first (same as the website):
    an area below its stage minimum comes first, the furthest below;
    otherwise the area with the largest weighted shortfall,
    weight x (100 - score). scores: {dim_key: 0-100}."""
    if not scores:
        return None
    under = {k: gates[k] - s for k, s in scores.items() if k in gates and s < gates[k]}
    if under:
        k = max(under, key=under.get)
        return {"key": k, "score": scores[k], "why": "below-minimum", "minimum": gates[k]}
    k = max(scores, key=lambda d: weights.get(d, 10) * (100 - scores[d]))
    return {"key": k, "score": scores[k], "why": "weighted"}


def validation_summary(pairs, outcomes):
    """pairs: [{"self": {dim: pct}, "verified": {dim: score}, "selfGap": dim|None, "verifiedGap": dim|None}]
    outcomes: [{"kind", "overall"}]."""
    per = {}
    for p in pairs:
        for k, sv in p["self"].items():
            vv = p["verified"].get(k)
            if vv is None:
                continue
            d = per.setdefault(k, {"n": 0, "sum": 0.0, "abs": 0.0})
            d["n"] += 1
            d["sum"] += sv - vv
            d["abs"] += abs(sv - vv)
    by_dim = {k: {"clients": d["n"], "avgSelfMinusVerified": round(d["sum"] / d["n"], 1),
                  "avgAbsoluteGap": round(d["abs"] / d["n"], 1)} for k, d in per.items()}
    gap_pairs = [p for p in pairs if p.get("selfGap") and p.get("verifiedGap")]
    agree = sum(1 for p in gap_pairs if p["selfGap"] == p["verifiedGap"])
    bands = {}
    for o in outcomes:
        ov = o.get("overall")
        band = "unknown" if ov is None else ("under 50" if ov < 50 else "50 to 74" if ov < 75 else "75 and up")
        b = bands.setdefault(band, {})
        b[o["kind"]] = b.get(o["kind"], 0) + 1
    return {
        "clientsWithBoth": len(pairs),
        "byDimension": by_dim,
        "gapAgreement": {"clients": len(gap_pairs), "matched": agree,
                         "rate": round(agree / len(gap_pairs), 2) if gap_pairs else None},
        "outcomes": {"logged": len(outcomes), "byScoreBand": bands},
        "enoughData": len(pairs) >= 10,
        "note": "Read with care until at least 10 clients have both scores. A positive average means leaders rated themselves higher than the evidence showed.",
    }
