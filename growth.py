"""
Growth Pathway: which size stage an organization is in, how ready it is to
grow, and what to do next.

This is separate from the Health Index lifecycle (BUILD / FUND / SUSTAIN in
scoring.py). That says what kind of work the organization is doing; this
says how big it is and whether its structure, money, fundraising, board and
compliance are ready for the next size up. The stages, gates and figures
come from Frankly Inspired's scaling guide (Nov 2026):

    1 Founder-led   under $250K
    2 Emerging      $250K to $1M
    3 Established   $1M to $5M
    4 Large         $5M to $20M
    5 Very large    over $20M

Five pillars, each scored 0-4, make a Stage Readiness Score out of 20:
16+ ready to grow, 10-15 strengthen before adding staff, under 10
stabilize first. Anything not yet entered scores 0 and is listed under
"missing", so a low score from missing data reads differently from a low
score from real gaps.

Every input is optional. Salaries are planning figures for the DC, Maryland
and Virginia market; the report says so.
"""

FRINGE_RATE = 0.25
PERSONNEL_SHARE = 0.65

STAGES = [
    {"stage": 1, "name": "Founder-led", "min": 0, "max": 250_000, "staff": (0, 2),
     "boardType": "Founding / working board", "boardSize": (5, 7),
     "boardJob": "Hands-on: helps run programs, raises the first dollars, sets up books and policies",
     "fundraising": "Prove people will give: the founder's and board's networks, 100% board giving, "
                    "three to five local foundation grants, one peer-to-peer or GivingTuesday campaign",
     "contributedGoal": "$100K to $250K", "growthTarget": "25 to 50% a year"},
    {"stage": 2, "name": "Emerging", "min": 250_000, "max": 1_000_000, "staff": (3, 8),
     "boardType": "Moving to a governing board", "boardSize": (7, 11),
     "boardJob": "Hires and evaluates the ED, approves the budget, adopts a strategic plan, opens doors to donors",
     "fundraising": "Build the system: a grants calendar, two appeals a year, a second-gift program, "
                    "mid-level donors, and the ED's first $10K+ asks",
     "contributedGoal": "$300K to $900K", "growthTarget": "20 to 30% a year"},
    {"stage": 3, "name": "Established", "min": 1_000_000, "max": 5_000_000, "staff": (10, 40),
     "boardType": "Governing board", "boardSize": (11, 15),
     "boardJob": "Strategy, oversight, the audit, major-gift connections, ED succession",
     "fundraising": "Build major gifts: a development director with a portfolio of 150 or fewer qualified "
                    "donors, a planned giving launch, corporate partnerships",
     "contributedGoal": "$1M to $4M", "growthTarget": "10 to 20% a year"},
    {"stage": 4, "name": "Large", "min": 5_000_000, "max": 20_000_000, "staff": (40, 150),
     "boardType": "Institutional board", "boardSize": (15, 21),
     "boardJob": "Direction, campaigns, policy, CEO pay and performance; committees do the detail",
     "fundraising": "Campaigns and teams: major gift officers, a planned giving officer, an institutional giving team",
     "contributedGoal": "$4M to $15M", "growthTarget": "8 to 15% a year"},
    {"stage": 5, "name": "Very large", "min": 20_000_000, "max": None, "staff": (150, None),
     "boardType": "Institutional board with advisory boards", "boardSize": (15, 25),
     "boardJob": "Campaign and endowment leadership, risk, public standing",
     "fundraising": "Principal gifts, endowment and comprehensive campaigns",
     "contributedGoal": "$15M+", "growthTarget": "5 to 10% a year"},
]

# Hiring order per stage: (seat key, name, planning salary, FTE). A salary
# of None means "check benchmarks"; those seats still appear as next hires.
HIRES = {
    1: [("bookkeeper", "Contract bookkeeper", 7_500, 0),
        ("founder_paid", "Founder paid (part- to full-time)", 55_000, 1),
        ("program_coordinator", "Part-time program coordinator", 25_000, 0.5)],
    2: [("ed_full_time", "Full-time executive director at market pay", 75_000, 1),
        ("program_manager", "Program manager", 58_000, 1),
        ("development_coordinator", "Development / grants coordinator", 52_000, 1),
        ("operations_coordinator", "Operations / admin coordinator", 48_000, 1),
        ("program_staff", "Front-line program staff", 42_000, 1)],
    3: [("development_director", "Development director", 95_000, 1),
        ("program_director", "Program director", 90_000, 1),
        ("finance_manager", "Finance manager (+ fractional CFO)", 80_000, 1),
        ("hr_manager", "HR manager", 72_000, 1),
        ("communications_manager", "Communications manager", 65_000, 1),
        ("evaluation_manager", "Data and evaluation manager", 70_000, 1),
        ("operations_manager", "Office / operations manager", 60_000, 1)],
    4: [("coo", "Deputy ED / COO", 150_000, 1),
        ("cfo", "CFO, with a controller", 160_000, 1),
        ("chief_development_officer", "Chief development officer", 150_000, 1),
        ("hr_director", "HR director", 115_000, 1),
        ("grants_compliance_manager", "Grants compliance / contracts manager", 90_000, 1),
        ("it_manager", "IT manager or managed service", 105_000, 1)],
    5: [("chief_people_officer", "Chief people officer", None, 1),
        ("chief_technology_officer", "Chief information / technology officer", None, 1),
        ("general_counsel", "General counsel", None, 1),
        ("internal_audit", "Internal audit", None, 1),
        ("chief_strategy_officer", "Chief strategy / impact officer", None, 1)],
}

# Board policies, cumulative by stage.
POLICIES = {
    1: [("bylaws", "Bylaws"), ("conflict_of_interest", "Conflict of interest policy"),
        ("whistleblower", "Whistleblower policy"), ("document_retention", "Document retention policy"),
        ("financial_controls", "Financial controls with two signers")],
    2: [("pay_setting", "ED pay-setting process with comparables"), ("reserve_policy", "Operating reserve policy"),
        ("gift_acceptance", "Gift acceptance policy"), ("board_agreements", "Board member agreements with give-or-get")],
    3: [("audit_committee_charter", "Audit committee charter"), ("term_limits", "Board term limits"),
        ("succession_plan", "ED succession plan"), ("board_self_assessment", "Yearly board self-assessment"),
        ("investment_policy", "Investment policy")],
    4: [("risk_management", "Enterprise risk management"), ("compensation_committee", "Executive pay committee"),
        ("campaign_policy", "Campaign and endowment policies"), ("committee_charters", "Charters for each standing committee")],
    5: [],
}

POLICY_NAMES = {k: n for lst in POLICIES.values() for k, n in lst}
SEAT_NAMES = {k: n for lst in HIRES.values() for k, n, _s, _f in lst}


def _num(v):
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "yes", "1"):
        return True
    if isinstance(v, str) and v.strip().lower() in ("false", "no", "0"):
        return False
    return None


def stage_for(budget):
    if budget is None:
        return None
    for s in STAGES:
        if s["max"] is None or budget < s["max"]:
            return s
    return STAGES[-1]


def policies_for(stage_no):
    out = []
    for n in range(1, stage_no + 1):
        out += POLICIES.get(n, [])
    return out


def hire_cost(salary, fte):
    if salary is None:
        return None
    wages = salary * (fte or 1)
    loaded = wages * (1 + FRINGE_RATE) if fte else wages  # a contract seat has no benefits
    return {"salary": salary, "fte": fte, "loadedCost": round(loaded),
            "budgetRequired": round(loaded / PERSONNEL_SHARE), "reserveAdd": round(loaded * 3 / 12)}


def merge_snapshot(inputs, snapshot):
    """Fill gaps from the latest filed financials. Entered values always win."""
    i = dict(inputs or {})
    est = []
    if snapshot:
        if _num(i.get("budget")) is None and snapshot.get("total_expenses"):
            i["budget"] = snapshot["total_expenses"]
            est.append("budget")
        exp = snapshot.get("total_expenses") or 0
        if _num(i.get("reserve_months")) is None and snapshot.get("net_assets") is not None and exp:
            # Net assets include restricted funds and property, so this
            # overstates true operating reserves; flagged as an estimate.
            i["reserve_months"] = round(max(snapshot["net_assets"], 0) / (exp / 12), 1)
            est.append("reserve_months")
        pol = set(i.get("policies") or [])
        for key, col in (("conflict_of_interest", "conflict_of_interest_policy"),
                         ("whistleblower", "whistleblower_policy"),
                         ("document_retention", "document_retention_policy")):
            if snapshot.get(col) is True:
                pol.add(key)
        i["policies"] = sorted(pol)
        if _num(i.get("board_size")) is None and snapshot.get("governing_body_voting_members"):
            i["board_size"] = snapshot["governing_body_voting_members"]
            est.append("board_size")
    return i, est


def assess(inputs, snapshot=None):
    i, estimated = merge_snapshot(inputs, snapshot)
    missing = []

    def need(key, label):
        v = i.get(key)
        if v is None or v == "" or (isinstance(v, list) and not v and key != "policies"):
            missing.append(label)
            return None
        return v

    budget = _num(need("budget", "Annual budget (expenses)"))
    st = stage_for(budget)
    if not st:
        return {"stage": None, "stageName": None, "score": None, "band": None,
                "missing": ["Annual budget (expenses)"],
                "note": "Enter the annual budget, or ingest a 990, to place the organization in a stage."}
    n = st["stage"]
    nxt = STAGES[n] if n < 5 else None

    staff = _num(need("staff_fte", "Staff (full-time equivalents)"))
    reserves = _num(need("reserve_months", "Months of operating reserves"))
    personnel = _num(need("personnel_share", "Personnel share of expenses (%)"))
    largest = _num(need("largest_source_share", "Largest funding source share (%)"))
    c_actual = _num(need("contributed_actual", "Contributed revenue this year"))
    c_goal = _num(need("contributed_goal", "Contributed revenue goal"))
    retention = _num(need("donor_retention", "Donor retention (%)"))
    cpd = _num(need("cost_per_dollar", "Cost per dollar raised"))
    fr_plan = _bool(need("fundraising_plan", "Written fundraising plan (yes/no)"))
    board_size = _num(need("board_size", "Board size"))
    board_giving = _num(need("board_giving_pct", "Board members who give (%)"))
    ed_eval = _bool(need("ed_evaluated", "ED evaluated in writing this year (yes/no)"))
    filings = _bool(need("filings_current", "990 and state registration current (yes/no)"))
    ed_seats = _num(i.get("ed_seat_count"))
    filled = set(i.get("filled_seats") or [])
    adopted = set(i.get("policies") or [])

    # 1. Structure
    seats = HIRES[n]
    have = sum(1 for k, *_ in seats if k in filled)
    frac = have / len(seats) if seats else 1
    structure = (2 if frac >= 0.75 else 1 if frac >= 0.4 else 0)
    lo, hi = st["staff"]
    if staff is not None and staff >= lo:
        structure += 1
    if ed_seats is not None and ed_seats <= 3:
        structure += 1
    elif ed_seats is None:
        missing.append("Seats the ED holds")
    structure = min(structure, 4)

    # 2. Money
    money = 0
    if reserves is not None:
        money += 2 if reserves >= 3 else 1 if reserves >= 1.5 else 0
    if personnel is not None and 55 <= personnel <= 70:
        money += 1
    if largest is not None and largest <= 40:
        money += 1

    # 3. Fundraising
    fund = 0
    if c_actual is not None and c_goal:
        fund += 1 if c_actual >= 0.9 * c_goal else 0
    if retention is not None and retention >= 45:
        fund += 1
    if cpd is not None and cpd <= 0.25:
        fund += 1
    if fr_plan:
        fund += 1

    # 4. Board
    blo, bhi = st["boardSize"]
    req_policies = policies_for(n)
    missing_policies = [name for k, name in req_policies if k not in adopted]
    board = 0
    if board_size is not None and board_size >= blo:
        board += 1
    if board_giving is not None and board_giving >= 100:
        board += 1
    if ed_eval:
        board += 1
    if not missing_policies:
        board += 1

    # 5. Compliance: thresholds that apply now must be met; ones that don't
    # apply yet count as met.
    comp = 0
    if filings:
        comp += 1
    contributions = _num(i.get("contributions")) or c_actual
    review_needed = contributions is not None and contributions >= 400_000
    if not review_needed or _bool(i.get("audit_or_review_done")):
        comp += 1
    if (staff or 0) < 15 or _bool(i.get("employee_handbook")):
        comp += 1
    if _bool(i.get("indirect_rate_set")) or _bool(i.get("cost_allocation")):
        comp += 1
    elif i.get("indirect_rate_set") is None and i.get("cost_allocation") is None:
        missing.append("Indirect cost rate or cost allocation in place (yes/no)")

    pillars = [
        {"key": "structure", "name": "Structure", "score": structure,
         "measures": f"{have} of {len(seats)} stage {n} seats filled" + (f"; ED holds {int(ed_seats)} seats" if ed_seats is not None else "")},
        {"key": "money", "name": "Money", "score": money,
         "measures": "; ".join(x for x in [
             f"{reserves:g} months of reserves" if reserves is not None else "",
             f"personnel {personnel:g}% of expenses" if personnel is not None else "",
             f"largest source {largest:g}%" if largest is not None else ""] if x)},
        {"key": "fundraising", "name": "Fundraising", "score": fund,
         "measures": "; ".join(x for x in [
             f"{round(100 * c_actual / c_goal)}% of contributed goal" if c_actual is not None and c_goal else "",
             f"retention {retention:g}%" if retention is not None else "",
             f"${cpd:.2f} per dollar raised" if cpd is not None else ""] if x)},
        {"key": "board", "name": "Board", "score": board,
         "measures": "; ".join(x for x in [
             f"{int(board_size)} members (stage {n} range {blo} to {bhi})" if board_size is not None else "",
             f"{board_giving:g}% give" if board_giving is not None else "",
             f"{len(req_policies) - len(missing_policies)} of {len(req_policies)} policies"] if x)},
        {"key": "compliance", "name": "Compliance", "score": comp, "measures": ""},
    ]
    for p in pillars:
        p["ready"] = p["score"] >= 3
    total = sum(p["score"] for p in pillars)
    band = ("Ready to grow" if total >= 16 else
            "Strengthen before adding staff" if total >= 10 else "Stabilize first")

    # Next two hires: this stage's open seats first, then the next stage's.
    order = HIRES[n] + (HIRES[n + 1] if n < 5 else [])
    next_hires = []
    for k, name, sal, fte in order:
        if k in filled:
            continue
        next_hires.append({"seat": k, "name": name, **(hire_cost(sal, fte) or {"salary": None, "note": "Check Candid benchmarks"})})
        if len(next_hires) == 2:
            break

    board_gap = []
    if board_size is not None and board_size < blo:
        board_gap.append(f"Recruit {int(blo - board_size)} or more members toward {blo} to {bhi}")
    if nxt and board_size is not None and board_size < nxt["boardSize"][0]:
        board_gap.append(f"The next stage needs {nxt['boardSize'][0]} to {nxt['boardSize'][1]} members ({nxt['boardType'].lower()})")
    if board_giving is not None and board_giving < 100:
        board_gap.append("Get to 100% board giving")
    if ed_eval is False:
        board_gap.append("Evaluate the ED in writing this year")
    board_gap += [f"Adopt: {p}" for p in missing_policies]

    compliance_next = []
    if staff is not None:
        for at, what in ((15, "Title VII and the ADA apply"), (20, "COBRA and the Age Discrimination in Employment Act apply"),
                         (50, "FMLA and the ACA employer mandate apply"), (100, "EEO-1 reporting and the WARN Act apply")):
            if staff < at:
                compliance_next.append(f"At {at} employees: {what} (now about {staff:g})")
                break
    if contributions is not None:
        if contributions < 400_000:
            compliance_next.append("Maryland: a CPA review is required once contributions reach $400,000 (confirm the figure with the Secretary of State)")
        elif contributions < 1_000_000:
            compliance_next.append("Maryland: an independent audit is required once contributions reach $1 million")
    if budget < 200_000:
        compliance_next.append("A full Form 990 is required once receipts reach $200,000")

    if c_goal:
        goal_text = f"${c_goal:,.0f} this year"
    else:
        goal_text = st["contributedGoal"] + " (stage range)"

    return {
        "stage": n, "stageName": st["name"],
        "stageRange": f"${st['min']:,} to " + (f"${st['max']:,}" if st["max"] else "and up"),
        "nextStage": ({"stage": nxt["stage"], "name": nxt["name"], "at": nxt["min"]} if nxt else None),
        "score": total, "outOf": 20, "band": band,
        "pillars": pillars,
        "nextHires": next_hires,
        "fundraising": {"strategy": st["fundraising"], "goal": goal_text, "growthTarget": st["growthTarget"]},
        "board": {"type": st["boardType"], "size": f"{blo} to {bhi}", "job": st["boardJob"], "gaps": board_gap},
        "complianceNext": compliance_next,
        "missing": missing,
        "estimated": estimated,
        "note": "Planning guidance, not legal or accounting advice. Salaries are DC, Maryland and Virginia planning figures.",
    }


SEATS = [{"key": k, "name": n, "stage": s} for s, lst in HIRES.items() for k, n, _a, _b in lst]
POLICY_LIST = [{"key": k, "name": n, "stage": s} for s, lst in POLICIES.items() for k, n in lst]
