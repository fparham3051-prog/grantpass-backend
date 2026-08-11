"""
Readiness scoring: the same 8-dimension rubric used in the front-end demo,
now computed server-side.

Financial Health is scored deterministically from real ingested 990 data
(reserve months, revenue concentration, revenue-vs-expense surplus) - no AI
call needed, no hand-waving. The other 7 dimensions require judgment calls
that either need a human to enter them (POST /orgs/{id}/dimensions) or an
LLM in the loop (this backend has no LLM API key wired up - see README) -
they default to a neutral 50 until scored, which is intentionally visible
rather than silently assumed.
"""

RUBRIC = [
    {"key": "legal", "name": "Legal & Compliance", "weight": 15},
    {"key": "financial", "name": "Financial Health", "weight": 20},
    {"key": "governance", "name": "Governance", "weight": 10},
    {"key": "strategy", "name": "Strategic Clarity", "weight": 10},
    {"key": "trackRecord", "name": "Track Record", "weight": 15},
    {"key": "outcomes", "name": "Outcome Measurement", "weight": 15},
    {"key": "leadership", "name": "Leadership Stability", "weight": 5},
    {"key": "reporting", "name": "Reporting Capacity", "weight": 10},
]

NAME_TO_KEY = {d["name"]: d["key"] for d in RUBRIC}


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


def compute_overall(dimension_scores: dict) -> float:
    total_weight = sum(d["weight"] for d in RUBRIC)
    overall = sum(dimension_scores.get(d["key"], 50) * d["weight"] for d in RUBRIC) / total_weight
    return round(overall, 1)


def level_for(score: float) -> str:
    if score >= 75:
        return "green"
    if score >= 55:
        return "yellow"
    return "red"


def status_for(overall: float) -> str:
    if overall >= 75:
        return "Ready"
    if overall >= 55:
        return "Needs Work"
    return "Not Ready"
