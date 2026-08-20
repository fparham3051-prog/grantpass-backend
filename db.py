"""
Postgres persistence layer (Neon). Real, hosted, relational - not
localStorage, not local SQLite (Render's free web-service tier has no
persistent disk, so an on-disk SQLite file gets wiped on every deploy and
likely every idle spin-down; Neon's free Postgres tier survives both).

Schema mirrors the data model from the GrantPass spec: Organization,
FinancialSnapshot (from ingested 990 data), ReadinessScore, Funder,
ReportEntry (the continuous-reporting history).

server.py's ~40 query call sites were written against sqlite3's API:
conn.execute(sql, params) returning a cursor you fetchone()/fetchall() on
directly, with dict-like Row access (row["col"], dict(row)). Rather than
rewrite every call site for psycopg2's different API, PGConnection below
presents that same sqlite3-shaped surface backed by psycopg2 - so almost
none of server.py needed to change. The one real behavioral gap is
cursor.lastrowid, which Postgres doesn't have; the handful of INSERT call
sites that used it were updated to add RETURNING id and read
cur.fetchone()["id"] instead - see server.py's _register, _create_org,
_create_compliance, _create_funder, _ingest_donor_sustainability.

Requires DATABASE_URL to be set (a full postgres:// connection string).
"""
import os
import datetime

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_KIND = "postgres"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS organizations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    ein TEXT,
    description TEXT,
    share_token TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS financial_snapshots (
    id SERIAL PRIMARY KEY,
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
    id SERIAL PRIMARY KEY,
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
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    name TEXT NOT NULL,
    focus TEXT,
    grant_range TEXT,
    approach TEXT,
    weights_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_entries (
    id SERIAL PRIMARY KEY,
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
-- also the first piece of genuinely proprietary data this system produces -
-- nothing here is derivable from public 990 data.
CREATE TABLE IF NOT EXISTS outcomes (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id),
    funder_name TEXT NOT NULL,
    result TEXT NOT NULL,
    amount REAL,
    score_at_time REAL,
    notes TEXT,
    logged_at TEXT NOT NULL
);

-- Raw responses from the standalone "Donor Sustainability & Stewardship
-- Assessment" Google Form, pushed here by an Apps Script onFormSubmit
-- trigger. Deliberately NOT foreign-keyed to organizations(id): the form
-- captures org_name as free text from whoever fills it out, so there's no
-- guaranteed match to an authenticated user's org record at ingest time.
-- This is a second, complementary rubric (donor retention/stewardship) -
-- not a straight substitute for one of the 7 manual_dimensions keys - so it
-- gets its own table rather than being folded into manual_dimensions.
-- org_id stays nullable for a later manual/fuzzy-match linking step.
CREATE TABLE IF NOT EXISTS donor_sustainability_responses (
    id SERIAL PRIMARY KEY,
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
    id SERIAL PRIMARY KEY,
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


def _translate(sql):
    """server.py's call sites are written against sqlite3's '?' placeholder
    style. None of the queries embed a literal '?' character outside of
    placeholders, so a straight replace to psycopg2's '%s' style is safe."""
    return sql.replace("?", "%s")


class _Cursor:
    """Wraps a psycopg2 RealDictCursor so callers can keep doing
    cur.fetchone()/cur.fetchall() and get dict-like rows (row["col"],
    dict(row), "key" in row) exactly like sqlite3.Row gave them."""

    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def lastrowid(self):
        # Postgres cursors have no lastrowid - call sites that need the
        # new row's id use "... RETURNING id" in the INSERT and read it
        # via fetchone()["id"] instead. If this raises, a call site was
        # missed during the SQLite -> Postgres migration.
        raise AttributeError(
            "Postgres cursors have no lastrowid - use RETURNING id + fetchone() instead"
        )


class PGConnection:
    """Thin sqlite3.Connection-shaped wrapper around a psycopg2 connection,
    so the query call sites throughout server.py didn't need a rewrite when
    the storage engine moved from SQLite to Postgres."""

    def __init__(self, pg_conn):
        self._conn = pg_conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(_translate(sql), params)
        return _Cursor(cur)

    def executescript(self, sql):
        cur = self._conn.cursor()
        cur.execute(sql)
        cur.close()

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_conn():
    pg_conn = psycopg2.connect(DATABASE_URL)
    return PGConnection(pg_conn)


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def now():
    return datetime.datetime.utcnow().isoformat()
