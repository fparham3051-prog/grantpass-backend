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
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def now():
    return datetime.datetime.utcnow().isoformat()
