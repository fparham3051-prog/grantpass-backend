"""
SQLite persistence layer. Real, on-disk, relational - not localStorage.

Schema mirrors the data model from the GrantPass spec: Organization,
FinancialSnapshot (from ingested 990 data), ReadinessScore, Funder,
ReportEntry (the continuous-reporting history).
"""
import sqlite3
import os
import datetime

DB_PATH = os.environ.get("GRANTPASS_DB", os.path.join(os.path.dirname(__file__), "grantpass.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    ein TEXT,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS financial_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    source TEXT NOT NULL,
    fiscal_year TEXT,
    total_revenue REAL,
    total_expenses REAL,
    total_assets REAL,
    net_assets REAL,
    contributions_revenue REAL,
    program_revenue REAL,
    ingested_at TEXT NOT NULL
);

-- Append-only history of computed overall scores (for trend/audit purposes).
CREATE TABLE IF NOT EXISTS readiness_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    overall REAL,
    status TEXT,
    dimensions_json TEXT,
    computed_at TEXT NOT NULL
);

-- Current-state manual (or future LLM-sourced) input for the 7 dimensions
-- that aren't derived from ingested financial data. One row per org,
-- upserted - deliberately separate from readiness_scores (history) so a
-- computed-score log entry can never shadow the latest manual input.
CREATE TABLE IF NOT EXISTS manual_dimensions (
    org_id INTEGER PRIMARY KEY REFERENCES organizations(id),
    dimensions_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS funders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    name TEXT NOT NULL,
    focus TEXT,
    grant_range TEXT,
    approach TEXT,
    weights_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    update_text TEXT NOT NULL,
    overall_before REAL,
    overall_after REAL,
    dimensions_json TEXT,
    created_at TEXT NOT NULL
);

-- Real-world funding outcomes tied to a specific org and (optionally) the
-- readiness score at the time the outcome is logged. This is the ground-truth
-- capture that lets the rubric eventually be validated or corrected against
-- actual funder decisions, instead of only ever scoring against itself. It's
-- also the first piece of genuinely proprietary data this system produces —
-- nothing here is derivable from public 990 data.
CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    funder_name TEXT NOT NULL,
    result TEXT NOT NULL,           -- 'funded' | 'declined' | 'pending'
    amount REAL,
    score_at_time REAL,             -- overall readiness score when this was logged, if known
    notes TEXT,
    logged_at TEXT NOT NULL
);

-- Raw responses from the standalone "Donor Sustainability & Stewardship
-- Assessment" Google Form, pushed here by an Apps Script onFormSubmit
-- trigger. Deliberately NOT foreign-keyed to organizations(id): the form
-- captures org_name as free text from whoever fills it out, so there's no
-- guaranteed match to an authenticated user's org record at ingest time.
-- This is a second, complementary rubric (donor retention/stewardship) —
-- not a straight substitute for one of the 7 manual_dimensions keys - so it
-- gets its own table rather than being folded into manual_dimensions.
-- org_id stays nullable for a later manual/fuzzy-match linking step.
CREATE TABLE IF NOT EXISTS donor_sustainability_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER REFERENCES organizations(id),
    org_name TEXT,
    respondent_role TEXT,
    grassroots_cultivation INTEGER,
    stewardship_infrastructure INTEGER,
    engagement_cadence INTEGER,
    first_gift_follow_through INTEGER,
    ownership_clarity INTEGER,
    board_readiness INTEGER,
    donor_data_maturity INTEGER,
    early_warning_capacity INTEGER,
    average_score REAL,
    evidence_json TEXT,
    final_notes TEXT,
    form_response_id TEXT,
    submitted_at TEXT NOT NULL
);

-- Compliance calendar: filing deadlines, policy review dates, board
-- approval cycles. Its own table (not folded into manual_dimensions)
-- because it's an ongoing operational checklist, not a point-in-time
-- score -- the thing Salesforce/Asana-style stacks don't give nonprofits:
-- one place to see what's due, when.
CREATE TABLE IF NOT EXISTS compliance_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    title TEXT NOT NULL,
    category TEXT,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    recurrence TEXT,
    notes TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL
);

"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    # Lightweight migration for columns added after initial deploy - SQLite
    # has no "ADD COLUMN IF NOT EXISTS", so just try and swallow the
    # duplicate-column error on databases that already have it.
    try:
        conn.execute("ALTER TABLE organizations ADD COLUMN share_token TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def now():
    return datetime.datetime.utcnow().isoformat()
