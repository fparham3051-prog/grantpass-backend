"""
Readiness scoring for all three InstitutionalOS Health Index Engine
lifecycle stages (BUILD, FUND, SUSTAIN) - same 7 dimensions everywhere,
different weights and go-thresholds per stage, exactly as specified in the
InstitutionalOS Health Index Engine v0.1 spec's "Master Institutional
Health Index Stage Weights" table.

Revenue and Financial Health is scored deterministically from real ingested
990 data (reserve months, revenue concentration, revenue-vs-expense surplus)
- no AI call needed, no hand-waving. The other 6 dimensions require
judgment calls that either need a human to enter them
(POST /orgs/{id}/dimensions) or an LLM in the loop (see demo_scoring.py) -
they default to a neutral 50 until scored, which is intentionally visible
rather than silently assumed, matching the spec's own "0 = Not in place"
versus "50 = Partial" evidence standard.

The authenticated /orgs flow (Console) is stage-aware end to end:
organizations.stage and readiness_scores.stage (see db.py) carry an org's
lifecycle stage through creation, scoring, and history, and score_org()
(server.py) scores against whichever of the three the org is actually in -
not just FUND. The public /demo/score endpoint accepts a `stage` argument
the same way, for a visitor who has no org yet.

Every manually-entered dimension (POST /orgs/{id}/dimensions) can also
carry the evidence that justifies its score - a note, and optionally a
source - stored alongside it in manual_dimensions.evidence_json and
surfaced by GET /orgs/{id}/full-report and GET /orgs/{id}/dimensions. A
score with nothing behind it stays visibly unsupported in the Console's
Evidence Vault view rather than reading the same as a well-documented one;
that distinction is the point, not an edge case to paper over.
"""

DIMENSIONS = [
    {"key": "strategy", "name": "Strategy and Positioning"},
    {"key": "program", "name": "Program and Impact Evidence"},
    {"key": "financial", "name": "Revenue and Financial Health"},
    {"key": "leadership", "name": "Leadership and Organizational Capacity"},
    {"key": "operations", "name": "Operations and Infrastructure"},
    {"key": "partnerships", "name": "Partnerships and Ecosystem"},
    {"key": "governance", "name": "Governance and Risk"},
]

# Per-stage weights, from the spec's Master Institutional Health Index
# Stage Weights table. Each stage's weights sum to 100.
STAGE_WEIGHTS = {
    "BUILD": {"strategy": 20, "program": 15, "financial": 10, "leadership": 15,
              "operations": 10, "partnerships": 10, "governance": 20},
    "FUND": {"strategy": 10, "program": 20, "financial": 20, "leadership": 10,
             "operations": 15, "partnerships": 10, "governance": 15},
    "SUSTAIN": {"strategy": 15, "program": 15, "financial": 20, "leadership": 15,
                "operations": 15, "partnerships": 10, "governance": 10},
}

# Hard gates, from the spec's "Decision gates" table. A stage's average can
# be high and still not clear its hard gate - the portfolio rule is
# "claims cannot outrun evidence." Red-risk flags (a documented unresolved
# risk) aren't collected by the freeform-text public demo, so the demo's
# hard-gate check only evaluates the numeric floors below; the full
# red-risk check is guided/advisory-tier work, done with Franklin directly.
HARD_GATES = {
    "BUILD": {"governance": 75, "strategy": 70},
    "FUND": {"governance": 75, "financial": 70, "program": 70},
    "SUSTAIN": {"governance": 70, "financial": 70, "leadership": 70},
}

DECISION_GATE = 75  # same "first major permission threshold" across all three stages

DEFAULT_STAGE = "FUND"

NAME_TO_KEY = {d["name"]: d["key"] for d in DIMENSIONS}


def rubric_for(stage: str = DEFAULT_STAGE):
    """Returns the DIMENSIONS list with each entry's weight filled in for
    the given stage - the shape existing callers (server.py, demo_scoring.py)
    already expect from the old flat RUBRIC constant."""
    weights = STAGE_WEIGHTS.get(stage, STAGE_WEIGHTS[DEFAULT_STAGE])
    return [{**d, "weight": weights[d["key"]]} for d in DIMENSIONS]


# Backward-compatible module-level constant: the FUND rubric, same shape
# code written against the old single-stage RUBRIC already expects.
RUBRIC = rubric_for(DEFAULT_STAGE)


def score_financial_health(snapshot: dict | None):
    """Returns (score 0-100, human-readable note), computed from real numbers."""
    if not snapshot or snapshot.get("total_revenue") is None:
        return 50, "No verified financial data ingested yet (POST /orgs/{id}/ingest-990) — neutral default."

    revenue = snapshot.get("total_revenue") or 0
    expenses = snapshot.get("total_expenses") or 0
    net_assets = snapshot.get("net_assets") or 0
    contributions = snapshot.get("contributions_revenue") or 0
    program = snapshot.get("program_revenue") or 0

    monthly_expenses = (expenses / 12) if expenses else 0
    reserve_months = (net_assets / monthly_expenses) if monthly_expenses > 0 else 0

    concentration = (max(contributions, program) / revenue) if revenue > 0 else 0

    reserve_score = min(100, (reserve_months / 6) * 100)  # 6+ months reserves = full marks
    concentration_score = 100 if concentration <= 0.5 else max(0, 100 - ((concentration - 0.5) / 0.5) * 100)
    surplus_score = 100 if revenue >= expenses else max(0, 100 - ((expenses - revenue) / max(revenue, 1)) * 200)

    score = round((reserve_score * 0.4) + (concentration_score * 0.35) + (surplus_score * 0.25))
    score = max(0, min(100, score))
    note = (
        f"From filed financial data: ~{reserve_months:.1f} months of operating reserves, "
        f"{concentration * 100:.0f}% revenue concentration in top source, "
        f"{'surplus' if revenue >= expenses else 'deficit'} of ${abs(revenue - expenses):,.0f}."
    )
    return score, note


def compute_overall(dimension_scores: dict, stage: str = DEFAULT_STAGE) -> float:
    weights = STAGE_WEIGHTS.get(stage, STAGE_WEIGHTS[DEFAULT_STAGE])
    total_weight = sum(weights.values())
    overall = sum(dimension_scores.get(key, 50) * w for key, w in weights.items()) / total_weight
    return round(overall, 1)


def level_for(score: float) -> str:
    if score >= 75:
        return "green"
    if score >= 55:
        return "yellow"
    return "red"


def status_for(overall: float) -> str:
    """Simple 3-band read, used by the existing color-coded UI (landing
    page, Console). See decision_band_for() for the spec's full 6-band
    scale."""
    if overall >= 75:
        return "Ready"
    if overall >= 55:
        return "Needs Work"
    return "Not Ready"


def decision_band_for(overall: float) -> dict:
    """The InstitutionalOS spec's full 6-band decision scale, from the
    'Decision gates' table: score band -> interpretation -> default
    decision. Returned alongside the simpler 3-band status_for() so a
    result can show either the quick read or the precise one."""
    bands = [
        (0, 59, "Assumption heavy", "Discover or repair"),
        (60, 69, "Promising but uncertain", "Test and develop"),
        (70, 74, "Material progress, some open risks", "Conditional go"),
        (75, 81, "Sufficient evidence for controlled execution", "Ready or proceed"),
        (82, 87, "Strong system evidence", "Launch or expand"),
        (88, 100, "Repeatable and well governed", "Scale"),
    ]
    for low, high, interpretation, decision in bands:
        if low <= overall <= high:
            return {"band": f"{low}-{high}", "interpretation": interpretation, "decision": decision}
    return {"band": None, "interpretation": None, "decision": None}


def lift_target(score: float) -> float:
    """The spec's 25% lift formula: Target = Current + 0.25 * (100 - Current).
    The next realistic evidence goal for one dimension, not an all-or-
    nothing bar."""
    return round(score + 0.25 * (100 - score), 2)


def hard_gate_check(dimension_scores: dict, stage: str = DEFAULT_STAGE) -> dict:
    """Numeric-only hard gate check for the given stage (see HARD_GATES).
    Does not evaluate red-risk flags - the freeform public demo doesn't
    collect those; a clean numeric pass here means 'no numeric gate is
    open', not 'guaranteed clear of every risk'."""
    gates = HARD_GATES.get(stage, HARD_GATES[DEFAULT_STAGE])
    open_gates = [
        {"dimension": key, "required": floor, "actual": dimension_scores.get(key, 50)}
        for key, floor in gates.items()
        if dimension_scores.get(key, 50) < floor
    ]
    return {
        "gates": gates,
        "open": open_gates,
        "status": "Open" if open_gates else "Met",
        "note": (
            "Numeric floors only — a documented unresolved red risk can still block a "
            "move-forward decision even when every numeric gate is met; that check is "
            "part of the full guided Review, not this self-service scorecard."
        ),
    }
