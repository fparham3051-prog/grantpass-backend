"""
Freeform-description scoring for the public InstitutionalOS "Analyze
Readiness" demo (the FUND lifecycle stage of the InstitutionalOS Health
Index Engine - see the master spec for BUILD/FUND/SUSTAIN and all three
stages' shared 7-dimension model).

Unlike /orgs/{id}/score - which requires an authenticated account, an
ingested 990, and manually-entered dimension values - this takes a single
paragraph describing an organization and returns the same FUND scorecard,
so a visitor gets a real answer with zero setup. This is deliberately the
"self-service" tier of the spec's three-tier model (self-service / guided
review / advisory) - a lighter proxy for the full 28-question, evidence-
linked FUND assessment Franklin runs directly with a client.

Two scoring paths, tried in order:
  1. Claude-based (if ANTHROPIC_API_KEY is set): the model reads the
     paragraph and estimates each dimension, told explicitly to score only
     from what's actually stated and never invent facts.
  2. Deterministic heuristic (always available, zero cost): regex/keyword
     detectors per dimension, approximating the same signals the full
     FUND question set asks about.

Every dimension defaults to 50 ("no data yet") when nothing relevant is
found in the text - same convention scoring.py uses server-side, and the
same meaning as the spec's own "Partial" 0-4 band - so a short or vague
description reads as "unscored," never as a fabricated guess.
"""
import json
import os
import re
import urllib.request
import urllib.error

import scoring

MIN_CHARS = 40
MAX_CHARS = 6000


# ---------- heuristic path ----------

def _find_percent_concentration(text):
    m = re.search(r"(\d{1,3})\s*%[^.]{0,40}?(from a single|from one|single (source|county|foundation|grant|donor|funder))", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(from a single|from one)[^.]{0,40}?(\d{1,3})\s*%", text, re.I)
    if m:
        return int(m.group(2))
    return None


def _find_reserve_months(text):
    m = re.search(r"(\d+(?:\.\d+)?)\s*(weeks?|months?)\s*(?:of\s*)?(?:operating\s*)?reserves?", text, re.I)
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2).lower()
    return n / 4.33 if unit.startswith("week") else n


def _find_years_operating(text):
    m = re.search(r"(?:operated|operating|running|in operation)\s*(?:for)?\s*(\d+)\s*years?", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)[- ]year[- ]old", text, re.I)
    if m:
        return int(m.group(1))
    return None


def _find_board_meetings_per_year(text):
    words_to_num = {"once": 1, "twice": 2, "quarterly": 4, "monthly": 12, "annually": 1}
    # "meets twice a year" / "meets 3 times a year" / "meets 4x a year"
    m = re.search(
        r"board[^.]{0,40}?meets?\s*(once|twice|quarterly|monthly|annually|\d+\s*times?|\d+\s*x)\s*(?:a|per)\s*year",
        text, re.I,
    )
    if m:
        raw = m.group(1).lower().strip()
        if raw in words_to_num:
            return words_to_num[raw]
        digits = re.search(r"\d+", raw)
        if digits:
            return int(digits.group())
    if re.search(r"board[^.]{0,40}?meets?\s*quarterly", text, re.I):
        return 4
    if re.search(r"board[^.]{0,40}?meets?\s*monthly", text, re.I):
        return 12
    return None


def _score_strategy(text):
    """Strategy and Positioning: case for support, funding priorities,
    funder fit, grant calendar - approximated here by whether a strategic
    plan exists and whether it's current."""
    score, notes = 50, []
    if re.search(r"strategic plan[^.]{0,30}(\boutdated\b|\bold\b|\bdated\b|hasn't been updated|has not been updated)", text, re.I):
        score -= 10
        notes.append("strategic plan exists but is dated")
    elif re.search(r"strategic plan", text, re.I):
        score += 15
        notes.append("strategic plan mentioned")
    if re.search(r"(target|priority) funders?|funder fit|grant calendar|case for support", text, re.I):
        score += 10
        notes.append("funder targeting/case-for-support language mentioned")
    if not notes:
        notes.append("no strategic plan or funder-targeting details found in the description")
    return max(0, min(100, score)), "; ".join(notes).capitalize() + "."


def _score_program(text):
    """Program and Impact Evidence: outcome framework, evidence, logic
    model - vs. activity counts alone. Years-operating is folded in here
    as a soft signal (more operating history usually means more outcome
    history), not scored on its own."""
    score, notes = 50, []
    neg = (
        re.search(r"(don'?t|do not|doesn'?t|not yet|haven'?t|has not)[^.]{0,60}(measure|track)[^.]{0,40}outcome", text, re.I)
        or re.search(r"outcome\w*[^.]{0,60}(don'?t|do not|doesn'?t|not yet|haven'?t|has not)", text, re.I)
        or re.search(r"no outcome data", text, re.I)
    )
    pos = re.search(r"(track|measure)[^.]{0,40}outcome", text, re.I) or re.search(
        r"outcome\w*[^.]{0,40}(track|measure|tied to mission)", text, re.I
    )
    activity_only = re.search(r"(track|measure)[^.]{0,60}(how many|number of)[^.]{0,60}(meals|people|attend|serve)", text, re.I)

    if neg:
        score -= 25
        notes.append("no outcome data beyond activity counts")
    elif pos:
        score += 15
        notes.append("outcome tracking mentioned")
    elif activity_only:
        score -= 10
        notes.append("activity counts tracked, but not outcomes")
    else:
        notes.append("no outcome measurement details found in the description")

    years = _find_years_operating(text)
    if years is not None:
        if years >= 3:
            score += 5
            notes.append(f"{years} years operating — more time to accumulate outcome evidence")
        else:
            score -= 5
            notes.append(f"only {years} years operating — limited outcome history so far")

    if re.search(r"(publish|share)[^.]{0,40}(impact|outcome|result)|annual (impact )?report", text, re.I):
        score += 10
        notes.append("outcomes are communicated externally (impact report or similar), not just tracked internally")
    elif re.search(r"(don'?t|do not|doesn'?t|no)[^.]{0,40}(publish|share)[^.]{0,20}(impact|outcome|result)", text, re.I):
        score -= 10
        notes.append("outcomes tracked but not communicated externally to donors")
    return max(0, min(100, score)), "; ".join(notes).capitalize() + "."


def _score_financial(text):
    score, notes = 50, []
    concentration = _find_percent_concentration(text)
    reserves = _find_reserve_months(text)
    audited = re.search(r"\baudited\b", text, re.I) and not re.search(
        r"no audited|not audited|don't have audited|do not have audited", text, re.I
    )
    bookkeeper_only = re.search(r"bookkeeper[- ]prepared|no audited|not audited", text, re.I)

    if audited:
        score += 15
        notes.append("audited financials mentioned")
    elif bookkeeper_only:
        score -= 20
        notes.append("no audited/reviewed financials — bookkeeper-prepared only")

    if concentration is not None:
        if concentration > 70:
            score -= 25
            notes.append(f"{concentration}% of revenue from a single source (over the 70% concentration risk line)")
        else:
            score += 10
            notes.append(f"{concentration}% revenue concentration in top source — diversified")

    if reserves is not None:
        if reserves < 1:
            score -= 15
            notes.append(f"~{reserves:.1f} months of operating reserves")
        elif reserves <= 3:
            score -= 5
            notes.append(f"~{reserves:.1f} months of operating reserves (needs strengthening)")
        else:
            score += 15
            notes.append(f"~{reserves:.1f} months of operating reserves (healthy)")

    if re.search(r"(monthly|recurring) (donor|giving|gift)s?|sustainer program", text, re.I):
        score += 10
        notes.append("recurring/monthly giving program mentioned — measurably stickier revenue than one-time gifts")

    if not notes:
        notes.append("no financial detail (reserves, concentration, audit status) found in the description")
    return max(0, min(100, score)), "; ".join(notes).capitalize() + "."


def _score_leadership(text):
    """Leadership and Organizational Capacity: for FUND specifically this
    is about who owns grants/funder relationships and whether the org can
    manage awarded work - approximated here with the same single-point-of-
    failure / succession signals used across all three lifecycle stages."""
    score, notes = 50, []
    if re.search(r"(founder|executive director|\bed\b)[^.]{0,60}(leads everything|only one|sole|single point)", text, re.I) or \
       re.search(r"single point of[^.]{0,20}(leadership|failure)", text, re.I):
        score -= 20
        notes.append("single point of leadership failure")
    if re.search(r"succession plan", text, re.I):
        score += 15
        notes.append("succession plan mentioned")
    if re.search(r"deputy director|associate director|second[- ]in[- ]command", text, re.I):
        score += 10
        notes.append("leadership depth beyond one person mentioned")
    if not notes:
        notes.append("no leadership structure details found in the description")
    return max(0, min(100, score)), "; ".join(notes).capitalize() + "."


def _score_operations(text):
    """Operations and Infrastructure: grant readiness room, pipeline,
    submission workflow, post-award reporting - approximated here with
    reporting timeliness/manual-vs-systematic language."""
    score, notes = 50, []
    manual = re.search(r"report(ing)?[^.]{0,40}(manual|by hand|spreadsheet)", text, re.I)
    on_time = re.search(r"report(ing)?[^.]{0,20}on time", text, re.I)
    late = re.search(r"report(ing)?[^.]{0,20}(late|behind|overdue)", text, re.I)
    system = re.search(r"grants? management system|grant pipeline|crm", text, re.I)
    if late:
        score -= 20
        notes.append("reporting described as late/behind")
    elif on_time and manual:
        score -= 5
        notes.append("reporting is on time but manual")
    elif on_time:
        score += 15
        notes.append("reporting described as on time")
    if system:
        score += 10
        notes.append("grants management system/CRM mentioned")
    if re.search(r"gift acceptance policy|accept(?:s|ing)? (?:appreciated )?stock|donor.advised fund grants?|\bqcd\b|planned giving program", text, re.I):
        score += 10
        notes.append("complex/planned-gift acceptance capability mentioned (stock, DAF, or gift-acceptance policy)")
    if not notes:
        notes.append("no reporting process or grants-tracking system details found in the description")
    return max(0, min(100, score)), "; ".join(notes).capitalize() + "."


def _score_partnerships(text):
    """Partnerships and Ecosystem: funder relationship strategy, MOUs and
    letters of commitment, referral/philanthropic ecosystem, corporate vs.
    public vs. philanthropic portfolio thinking. Also checks two signals
    added from the free Institutional Advancement Score's own research
    (Cornell moves-management framework; wealth-transfer research on
    advisor/DAF-sponsor referral relationships) - see the August 2026
    research briefs."""
    score, notes = 50, []
    if re.search(r"\b(partner|partnership|mou|memorandum of understanding|coalition|collaborat\w*|referral)\b", text, re.I):
        score += 15
        notes.append("partnership/collaboration language mentioned")
    if re.search(r"(no|not|without)[^.]{0,30}(partner|partnership)", text, re.I):
        score -= 15
        notes.append("explicitly no partnership relationships mentioned")
    if re.search(r"moves management|donor pipeline|donor stages?|(identification|qualification|cultivation|solicitation)[^.]{0,40}stewardship", text, re.I):
        score += 15
        notes.append("moves-management/donor-pipeline stages mentioned")
    if re.search(r"donor.advised fund|\bdafs?\b|financial advisor|estate attorney|estate planner|community foundation", text, re.I):
        score += 10
        notes.append("professional-advisor or DAF-sponsor relationships mentioned")
    if not notes:
        notes.append("no partnership or ecosystem relationships found in the description")
    return max(0, min(100, score)), "; ".join(notes).capitalize() + "."


def _score_governance(text):
    """Governance and Risk: tax-exempt/fiscal-sponsorship status, filings,
    restricted-fund controls, claim approval - approximated here with
    bylaws/tax-exempt-status and board size/meeting-cadence signals, which
    is the closest general-governance proxy a freeform paragraph usually
    offers."""
    score, notes = 50, []
    if re.search(r"no (written )?bylaws", text, re.I):
        score -= 25
        notes.append("no written bylaws mentioned")
    elif re.search(r"bylaws", text, re.I):
        score += 15
        notes.append("bylaws mentioned")
    if re.search(r"501\(c\)\(3\)|501c3|tax[- ]exempt", text, re.I):
        score += 10
        notes.append("tax-exempt status mentioned")

    meetings = _find_board_meetings_per_year(text)
    if meetings is not None:
        if meetings < 2:
            score -= 20
            notes.append(f"board meets ~{meetings}x/year (below the 2x/year floor)")
        elif meetings < 4:
            score += 5
            notes.append(f"board meets ~{meetings}x/year")
        else:
            score += 10
            notes.append(f"board meets ~{meetings}x/year — active")
    m = re.search(r"board (?:has|of)\s*(\d+)\s*members?", text, re.I)
    if m:
        n = int(m.group(1))
        if n < 5:
            score -= 10
            notes.append(f"{n}-member board is small")
        else:
            score += 5
            notes.append(f"{n}-member board")

    if not notes:
        notes.append("no governance/compliance details found in the description")
    return max(0, min(100, score)), "; ".join(notes).capitalize() + "."


_HEURISTIC_SCORERS = {
    "strategy": _score_strategy,
    "program": _score_program,
    "financial": _score_financial,
    "leadership": _score_leadership,
    "operations": _score_operations,
    "partnerships": _score_partnerships,
    "governance": _score_governance,
}


def heuristic_dimension_scores(text: str) -> dict:
    return {key: fn(text) for key, fn in _HEURISTIC_SCORERS.items()}


# ---------- Claude path ----------

CLAUDE_PROMPT = """You are scoring a nonprofit organization's grant readiness (the FUND stage \
of the InstitutionalOS Health Index Engine) from a single self-description. Score each of \
these 7 dimensions from 0-100, based ONLY on what the description actually states. If the \
description doesn't mention something relevant to a dimension, score it 50 and say so in the \
note - never invent facts, numbers, or claims the description doesn't contain.

Dimensions (name: what it measures):
- strategy: Strategy and Positioning (case for support, funding priorities, funder fit, grant calendar)
- program: Program and Impact Evidence (outcome framework, evidence, logic model, approved claims)
- financial: Revenue and Financial Health (budgets, financial statements, revenue concentration, cost allocation)
- leadership: Leadership and Organizational Capacity (named grants owner, approval workflow, board's fundraising role, capacity to manage awarded work)
- operations: Operations and Infrastructure (grant readiness room/document repository, pipeline tracking, submission workflow, post-award reporting)
- partnerships: Partnerships and Ecosystem (funder relationship strategy, MOUs/letters of commitment, referral network, funding-portfolio diversity)
- governance: Governance and Risk (tax-exempt/fiscal-sponsorship status, required filings, restricted-fund controls, claim approval protocol)

Respond with ONLY a JSON object, no other text, shaped exactly like:
{"strategy": {"score": 0-100, "note": "one sentence"}, "program": {...}, "financial": {...}, "leadership": {...}, "operations": {...}, "partnerships": {...}, "governance": {...}}

Organization description:
\"\"\"%s\"\"\"
"""


STAGE_CORE_QUESTIONS = {
    "BUILD": "Should this organization exist, and what must become true before launch?",
    "FUND": "Is the organization genuinely ready to pursue and manage institutional funding?",
    "SUSTAIN": "Can the institution operate, adapt, and endure?",
}


def claude_dimension_scores(text: str, stage: str = "FUND"):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    model = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
    stage_note = STAGE_CORE_QUESTIONS.get(stage, STAGE_CORE_QUESTIONS["FUND"])
    prompt_text = f"InstitutionalOS lifecycle stage: {stage} — core question: {stage_note}\n\n" + (CLAUDE_PROMPT % text)
    payload = json.dumps({
        "model": model,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt_text}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode())
        raw_text = body["content"][0]["text"]
        raw_text = re.sub(r"^```(json)?|```$", "", raw_text.strip(), flags=re.M).strip()
        parsed = json.loads(raw_text)
        out = {}
        for d in scoring.RUBRIC:
            key = d["key"]
            entry = parsed.get(key) or {}
            score = entry.get("score", 50)
            try:
                score = max(0, min(100, int(round(float(score)))))
            except (TypeError, ValueError):
                score = 50
            note = entry.get("note") or "No note returned."
            out[key] = (score, note)
        return out
    except Exception:
        return None


# ---------- combined ----------

def score_description(description: str, stage: str = scoring.DEFAULT_STAGE) -> dict:
    text = (description or "").strip()
    stage = stage if stage in scoring.STAGE_WEIGHTS else scoring.DEFAULT_STAGE
    dims_raw = claude_dimension_scores(text, stage)
    method = "ai"
    if dims_raw is None:
        dims_raw = heuristic_dimension_scores(text)
        method = "heuristic"

    dim_scores = {k: v[0] for k, v in dims_raw.items()}
    overall = scoring.compute_overall(dim_scores, stage)
    rubric = scoring.rubric_for(stage)
    dims = [
        {
            "key": d["key"],
            "name": d["name"],
            "weight": d["weight"],
            "score": dim_scores[d["key"]],
            "level": scoring.level_for(dim_scores[d["key"]]),
            "note": dims_raw[d["key"]][1],
            "liftTarget": scoring.lift_target(dim_scores[d["key"]]),
        }
        for d in rubric
    ]
    return {
        "stage": stage,
        "overall": overall,
        "status": scoring.status_for(overall),
        "decisionBand": scoring.decision_band_for(overall),
        "hardGate": scoring.hard_gate_check(dim_scores, stage),
        "dimensions": dims,
        "method": method,
    }
