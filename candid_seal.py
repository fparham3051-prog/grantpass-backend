"""Candid Seal of Transparency path for diagnostic clients.

Frankly Inspired does not issue its own seal. Every diagnostic's 90-day
plan includes the steps to the client's next Candid Seal level (Bronze,
Silver, Gold, Platinum), because the work Candid requires is the same work
the seven Health Index dimensions measure.

Requirements are summarized from Candid's 2026 Seals of Transparency guide
and must stay in step with the website's src/data/candidSeal.ts (the free
Candid Seal Path tool). Update both each year when Candid publishes a new
guide. Frankly Inspired is not affiliated with Candid.
"""

SEAL_YEAR = 2026
LEVELS = ["bronze", "silver", "gold", "platinum"]
LEVEL_NAMES = {"bronze": "Bronze", "silver": "Silver", "gold": "Gold", "platinum": "Platinum"}

# (level, what Candid asks for, Health Index dimension key, the step)
REQUIREMENTS = [
    ("bronze", "Claimed Candid profile", "governance", "Claim the free Candid profile and name a staff owner."),
    ("bronze", "Mission statement", "strategy", "Board adopts or reaffirms a written mission statement."),
    ("bronze", "Subject area, population, and geography served", "program", "Write who you serve, where, and in what field."),
    ("bronze", "Mailing address and website", "operations", "Confirm address and website match IRS records."),
    ("bronze", "Primary contact and leader name, title, email", "leadership", "Name a profile contact; confirm the leader's details."),
    ("bronze", "Donation details: legal name, EIN, payment address", "financial", "Confirm legal name, EIN, and donation address."),
    ("silver", "Each program's name, description, geography, subject, population", "program", "Write a short description (or one-page logic model) for each program."),
    ("gold", f"Audited financials or Form 990/990-EZ/990-PF/990-N for {SEAL_YEAR - 2} or {SEAL_YEAR - 1}", "governance", "Upload the latest filed 990 or audit; get current if filings are late."),
    ("gold", "Leader demographics (voluntary; 'decline to state' accepted)", "leadership", "Leader completes the demographic fields."),
    ("platinum", "Board demographics (voluntary; 'decline to state' accepted)", "governance", "Run a short voluntary board demographic survey."),
    ("platinum", f"At least one quantitative impact metric with a {SEAL_YEAR - 1} value", "program", "Choose one outcome, measure it, and report the number."),
    ("platinum", "Goals, strategies, and what the organization aims to solve", "strategy", "Write and board-approve a one-page goals and strategies summary."),
]


def normalize(level):
    level = (level or "").strip().lower()
    return level if level in LEVELS else ""


def seal_path(current):
    """Current level, the next level, and that level's requirements."""
    current = normalize(current)
    if current == "platinum":
        return {"current": "platinum", "currentName": "Platinum", "next": None, "nextName": None,
                "steps": [], "note": "Keep Platinum by updating the Candid profile every year, with a new metric value."}
    nxt = LEVELS[LEVELS.index(current) + 1] if current else "bronze"
    steps = [{"requirement": r[1], "dimension": r[2], "step": r[3]} for r in REQUIREMENTS if r[0] == nxt]
    return {
        "current": current or None,
        "currentName": LEVEL_NAMES.get(current, "None yet"),
        "next": nxt,
        "nextName": LEVEL_NAMES[nxt],
        "steps": steps,
        "note": "Seals are earned in order and renewed yearly. Candid decides every Seal.",
    }
