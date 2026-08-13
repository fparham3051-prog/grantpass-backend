"""
GrantPass backend — real HTTP API, no framework dependency (pure stdlib
http.server), so it runs anywhere Python 3 runs with zero installs.

Run:
    python3 server.py
    (listens on http://0.0.0.0:8420 by default; override with PORT env var)

See README.md for the full API reference and curl examples.
"""
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import auth
import db
import parsing
import scoring

db.init_db()


def json_response(handler, status, payload):
    body = json.dumps(payload, default=str).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def get_auth_user(handler):
    header = handler.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    return auth.verify_token(header[7:])


def check_ingest_secret(handler) -> bool:
    """Shared-secret check for the Apps Script -> backend webhook. Separate
    from user Bearer auth: the Form has no logged-in GrantPass user behind
    it, just a script running on a trigger. Set GRANTPASS_INGEST_SECRET on
    the server and give the same value to the Apps Script trigger."""
    expected = os.environ.get("GRANTPASS_INGEST_SECRET")
    if not expected:
        return False
    provided = handler.headers.get("X-Ingest-Secret", "")
    return hmac_compare(provided, expected)


def hmac_compare(a: str, b: str) -> bool:
    import hmac as _hmac
    return _hmac.compare_digest(a or "", b or "")


def score_org(conn, org_id: int) -> dict:
    """Shared scoring logic used by /score and /funders/{id}/rank."""
    org = conn.execute("SELECT * FROM organizations WHERE id=?", (org_id,)).fetchone()
    if not org:
        return None
    snapshot = conn.execute(
        "SELECT * FROM financial_snapshots WHERE org_id=? ORDER BY ingested_at DESC LIMIT 1", (org_id,)
    ).fetchone()
    manual_row = conn.execute(
        "SELECT dimensions_json FROM manual_dimensions WHERE org_id=?", (org_id,)
    ).fetchone()

    manual_dims = {}
    if manual_row:
        try:
            manual_dims = json.loads(manual_row["dimensions_json"])
        except Exception:
            manual_dims = {}

    fin_score, fin_note = scoring.score_financial_health(dict(snapshot) if snapshot else None)

    dims = []
    dim_scores = {"financial": fin_score}
    for d in scoring.RUBRIC:
        if d["key"] == "financial":
            sc, note = fin_score, fin_note
        elif d["key"] in manual_dims:
            sc, note = manual_dims[d["key"]], "Manually entered / externally scored."
        else:
            sc, note = 50, "No data yet for this dimension — neutral default."
        dim_scores[d["key"]] = sc
        dims.append({"name": d["name"], "weight": d["weight"], "score": sc, "level": scoring.level_for(sc), "note": note})

    overall = scoring.compute_overall(dim_scores)
    return {
        "orgId": org_id,
        "orgName": org["name"],
        "overall": overall,
        "status": scoring.status_for(overall),
        "dimensions": dims,
        "dimensionScores": dim_scores,
        "financialSourced": bool(snapshot),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # quiet; comment out to debug

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(length) if length else b""

    def _read_json(self) -> dict:
        raw = self._read_body()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization")
        self.end_headers()

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def _route(self, method):
        path = urlparse(self.path).path
        try:
            if path == "/health":
                return json_response(self, 200, {"ok": True})
            if path == "/auth/register" and method == "POST":
                return self._register()
            if path == "/auth/login" and method == "POST":
                return self._login()
            if path == "/orgs" and method == "GET":
                return self._list_orgs()
            if path == "/orgs" and method == "POST":
                return self._create_org()

            m = re.match(r"^/orgs/(\d+)$", path)
            if m and method == "GET":
                return self._get_org(int(m.group(1)))

            m = re.match(r"^/orgs/(\d+)/ingest-990$", path)
            if m and method == "POST":
                return self._ingest_990(int(m.group(1)))

            m = re.match(r"^/orgs/(\d+)/ingest-financial-data$", path)
            if m and method == "POST":
                return self._ingest_financial_data(int(m.group(1)))

            m = re.match(r"^/orgs/(\d+)/financial-snapshot$", path)
            if m and method == "GET":
                return self._get_financial_snapshot(int(m.group(1)))

            m = re.match(r"^/orgs/(\d+)/dimensions$", path)
            if m and method == "POST":
                return self._set_dimensions(int(m.group(1)))

            m = re.match(r"^/orgs/(\d+)/score$", path)
            if m and method == "GET":
                return self._get_score(int(m.group(1)))

            m = re.match(r"^/orgs/(\d+)/full-report$", path)
            if m and method == "GET":
                return self._get_full_report(int(m.group(1)))

            m = re.match(r"^/orgs/(\d+)/reports$", path)
            if m and method == "POST":
                return self._add_report(int(m.group(1)))
            if m and method == "GET":
                return self._list_reports(int(m.group(1)))

            m = re.match(r"^/orgs/(\d+)/outcomes$", path)
            if m and method == "POST":
                return self._add_outcome(int(m.group(1)))
            if m and method == "GET":
                return self._list_outcomes(int(m.group(1)))

            if path == "/export" and method == "GET":
                return self._export_account()

            if path == "/funders" and method == "GET":
                return self._list_funders()
            if path == "/funders" and method == "POST":
                return self._create_funder()

            if path == "/donor-sustainability/ingest" and method == "POST":
                return self._ingest_donor_sustainability()
            if path == "/donor-sustainability" and method == "GET":
                return self._list_donor_sustainability()

            m = re.match(r"^/funders/(\d+)/rank$", path)
            if m and method == "GET":
                return self._rank_for_funder(int(m.group(1)))

            return json_response(self, 404, {"error": "not found"})
        except Exception as e:
            return json_response(self, 500, {"error": str(e)})

    # ---------- auth ----------
    def _register(self):
        data = self._read_json()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        if not email or len(password) < 8:
            return json_response(self, 400, {"error": "email and password (8+ chars) required"})
        conn = db.get_conn()
        if conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            conn.close()
            return json_response(self, 409, {"error": "email already registered"})
        salt, pwd_hash = auth.hash_password(password)
        cur = conn.execute(
            "INSERT INTO users (email, salt, password_hash, created_at) VALUES (?,?,?,?)",
            (email, salt, pwd_hash, db.now()),
        )
        conn.commit()
        user_id = cur.lastrowid
        conn.close()
        return json_response(self, 201, {"token": auth.make_token(user_id), "userId": user_id})

    def _login(self):
        data = self._read_json()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        conn = db.get_conn()
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        if not row or not auth.verify_password(password, row["salt"], row["password_hash"]):
            return json_response(self, 401, {"error": "invalid credentials"})
        return json_response(self, 200, {"token": auth.make_token(row["id"]), "userId": row["id"]})

    # ---------- orgs ----------
    def _create_org(self):
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        data = self._read_json()
        if not data.get("name"):
            return json_response(self, 400, {"error": "name required"})
        conn = db.get_conn()
        cur = conn.execute(
            "INSERT INTO organizations (user_id, name, ein, description, created_at) VALUES (?,?,?,?,?)",
            (user_id, data["name"], data.get("ein"), data.get("description"), db.now()),
        )
        conn.commit()
        org_id = cur.lastrowid
        conn.close()
        return json_response(self, 201, {"id": org_id, "name": data["name"]})

    def _list_orgs(self):
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT id, name, ein, description, created_at FROM organizations WHERE user_id=?", (user_id,)
        ).fetchall()
        conn.close()
        return json_response(self, 200, {"organizations": [dict(r) for r in rows]})

    def _get_org(self, org_id):
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        conn = db.get_conn()
        row = conn.execute("SELECT * FROM organizations WHERE id=? AND user_id=?", (org_id, user_id)).fetchone()
        conn.close()
        if not row:
            return json_response(self, 404, {"error": "not found"})
        return json_response(self, 200, dict(row))

    def _ingest_990(self, org_id):
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        body = self._read_body()
        try:
            parsed = parsing.parse_990_xml(body)
        except Exception as e:
            return json_response(self, 400, {"error": f"could not parse XML: {e}"})
        conn = db.get_conn()
        org = conn.execute("SELECT id FROM organizations WHERE id=? AND user_id=?", (org_id, user_id)).fetchone()
        if not org:
            conn.close()
            return json_response(self, 404, {"error": "org not found"})
        conn.execute(
            """INSERT INTO financial_snapshots
               (org_id, source, fiscal_year, total_revenue, total_expenses, total_assets,
                net_assets, contributions_revenue, program_revenue, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                org_id, "990", parsed.get("tax_year"), parsed.get("total_revenue"), parsed.get("total_expenses"),
                parsed.get("total_assets"), parsed.get("net_assets"), parsed.get("contributions_revenue"),
                parsed.get("program_revenue"), db.now(),
            ),
        )
        conn.commit()
        conn.close()
        return json_response(self, 200, {"ingested": parsed})

    def _get_financial_snapshot(self, org_id):
        """Returns the latest ingested financial snapshot for an org, or
        {"snapshot": null} if none has been ingested yet. Read-side
        counterpart to /ingest-990 and /ingest-financial-data - added
        specifically so export_to_excel.py (and anything else) can read back
        what was ingested instead of only being able to write it."""
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        conn = db.get_conn()
        org = conn.execute("SELECT id FROM organizations WHERE id=? AND user_id=?", (org_id, user_id)).fetchone()
        if not org:
            conn.close()
            return json_response(self, 404, {"error": "org not found"})
        snap = conn.execute(
            "SELECT * FROM financial_snapshots WHERE org_id=? ORDER BY ingested_at DESC LIMIT 1", (org_id,)
        ).fetchone()
        conn.close()
        return json_response(self, 200, {"snapshot": dict(snap) if snap else None})

    def _ingest_financial_data(self, org_id):
        """Accepts pre-parsed financial data as JSON - the same shape
        fetch_990.py / bulk_ingest.py produce from ProPublica's API - instead
        of raw 990 XML bytes like /ingest-990. Writes to the same
        financial_snapshots table so scoring treats both sources identically;
        the 'source' field on the row records where it actually came from."""
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        data = self._read_json()
        conn = db.get_conn()
        org = conn.execute("SELECT id FROM organizations WHERE id=? AND user_id=?", (org_id, user_id)).fetchone()
        if not org:
            conn.close()
            return json_response(self, 404, {"error": "org not found"})
        conn.execute(
            """INSERT INTO financial_snapshots
               (org_id, source, fiscal_year, total_revenue, total_expenses, total_assets,
                net_assets, contributions_revenue, program_revenue, ingested_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                org_id, data.get("source", "bulk"), data.get("fiscal_year"), data.get("total_revenue"),
                data.get("total_expenses"), data.get("total_assets"), data.get("net_assets"),
                data.get("contributions_revenue"), data.get("program_revenue"), db.now(),
            ),
        )
        conn.commit()
        conn.close()
        return json_response(self, 200, {"saved": data})

    def _set_dimensions(self, org_id):
        """Manual (or future LLM-sourced) scores for the 7 non-financial dimensions.
        Body: {"legal": 80, "governance": 60, "strategy": 70, "trackRecord": 65,
                "outcomes": 55, "leadership": 75, "reporting": 90}"""
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        data = self._read_json()
        conn = db.get_conn()
        org = conn.execute("SELECT id FROM organizations WHERE id=? AND user_id=?", (org_id, user_id)).fetchone()
        if not org:
            conn.close()
            return json_response(self, 404, {"error": "org not found"})
        conn.execute(
            "INSERT INTO manual_dimensions (org_id, dimensions_json, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(org_id) DO UPDATE SET dimensions_json=excluded.dimensions_json, updated_at=excluded.updated_at",
            (org_id, json.dumps(data), db.now()),
        )
        conn.commit()
        conn.close()
        return json_response(self, 200, {"saved": data})

    def _get_score(self, org_id):
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        conn = db.get_conn()
        org = conn.execute("SELECT id FROM organizations WHERE id=? AND user_id=?", (org_id, user_id)).fetchone()
        if not org:
            conn.close()
            return json_response(self, 404, {"error": "org not found"})
        result = score_org(conn, org_id)
        conn.execute(
            "INSERT INTO readiness_scores (org_id, overall, status, dimensions_json, computed_at) VALUES (?,?,?,?,?)",
            (org_id, result["overall"], result["status"], json.dumps({"dimensions": result["dimensions"]}), db.now()),
        )
        conn.commit()
        conn.close()
        return json_response(self, 200, result)

    # Human-readable labels for the 8 donor-sustainability dimensions, in the
    # same order they appear on the Google Form (sections 2-9). Kept here
    # rather than in db.py since it's presentation-only, not schema.
    DONOR_DIMENSION_LABELS = [
        ("grassroots_cultivation", "Grassroots Cultivation Culture"),
        ("stewardship_infrastructure", "Stewardship Infrastructure"),
        ("engagement_cadence", "Non-Transactional Engagement Cadence"),
        ("first_gift_follow_through", "First-Gift Follow-Through"),
        ("ownership_clarity", "Relationship Ownership Clarity"),
        ("board_readiness", "Board Fundraising Readiness"),
        ("donor_data_maturity", "Donor Data Maturity"),
        ("early_warning_capacity", "Early-Warning Capacity"),
    ]

        def _get_full_report(self, org_id):
        """Combined view for the dashboard: this org's GrantPass readiness
        score (financial + manual dimensions) alongside its most recent
        Donor Sustainability & Stewardship Assessment submission, if any.
        These are two separate rubrics fed by two separate intake paths
        (dashboard forms vs. the standalone Google Form), so this endpoint
        is purely a read-side join for display - it writes nothing and
        doesn't touch readiness_scores history the way GET /score does.

        Donor-sustainability responses are matched to this org by stored
        org_id when the ingest-time name match succeeded, OR by a live
        case-insensitive name match as a fallback for responses submitted
        before this org existed in GrantPass (or where the name didn't
        match exactly at ingest time)."""
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        conn = db.get_conn()
        org = conn.execute("SELECT * FROM organizations WHERE id=? AND user_id=?", (org_id, user_id)).fetchone()
        if not org:
            conn.close()
            return json_response(self, 404, {"error": "org not found"})

        readiness = score_org(conn, org_id)

        rows = conn.execute(
            """SELECT * FROM donor_sustainability_responses
               WHERE org_id=? OR (org_id IS NULL AND lower(org_name)=lower(?))
               ORDER BY submitted_at DESC""",
            (org_id, org["name"]),
        ).fetchall()
        conn.close()

        donor = {"hasData": False, "responseCount": 0, "latest": None, "averageScore": None,
                 "dimensions": [], "history": []}
        if rows:
            latest = dict(rows[0])
            scores_present = [r["average_score"] for r in rows if r["average_score"] is not None]
            donor["hasData"] = True
            donor["responseCount"] = len(rows)
            donor["averageScore"] = round(sum(scores_present) / len(scores_present), 1) if scores_present else None
            donor["latest"] = {
                "submittedAt": latest["submitted_at"],
                "respondentRole": latest["respondent_role"],
                "averageScore": latest["average_score"],
                "finalNotes": latest["final_notes"],
                "evidence": json.loads(latest["evidence_json"] or "{}"),
            }
            donor["dimensions"] = [
                {
                    "key": col, "name": label,
                    "rating": latest[col],
                    "score": round((latest[col] - 1) / 4 * 100, 1) if latest[col] is not None else None,
                }
                for col, label in self.DONOR_DIMENSION_LABELS
            ]
            donor["history"] = [
                {"submittedAt": r["submitted_at"], "averageScore": r["average_score"], "respondentRole": r["respondent_role"]}
                for r in rows
            ]

        return json_response(self, 200, {
            "org": {"id": org["id"], "name": org["name"]},
            "readiness": readiness,
            "donorSustainability": donor,
        })

    def _add_report(self, org_id):
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        data = self._read_json()
        conn = db.get_conn()
        org = conn.execute("SELECT id FROM organizations WHERE id=? AND user_id=?", (org_id, user_id)).fetchone()
        if not org:
            conn.close()
            return json_response(self, 404, {"error": "org not found"})
        conn.execute(
            "INSERT INTO report_entries (org_id, update_text, overall_before, overall_after, dimensions_json, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                org_id, data.get("updateText", ""), data.get("overallBefore"), data.get("overallAfter"),
                json.dumps(data.get("dimensions", {})), db.now(),
            ),
        )
        conn.commit()
        conn.close()
        return json_response(self, 201, {"saved": True})

    def _list_reports(self, org_id):
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT * FROM report_entries WHERE org_id=? ORDER BY created_at DESC", (org_id,)
        ).fetchall()
        conn.close()
        return json_response(self, 200, {"reports": [dict(r) for r in rows]})

    # ---------- outcomes (ground truth for the rubric) ----------
    def _add_outcome(self, org_id):
        """Body: {"funderName": str, "result": "funded"|"declined"|"pending",
        "amount": number?, "scoreAtTime": number?, "notes": str?}
        This is the data that eventually lets you check whether the rubric's
        scores actually predict who gets funded - log it every time you learn
        a real outcome, even manually, even for orgs you're advising outside
        this tool."""
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        data = self._read_json()
        if not data.get("funderName") or not data.get("result"):
            return json_response(self, 400, {"error": "funderName and result required"})
        if data["result"] not in ("funded", "declined", "pending"):
            return json_response(self, 400, {"error": "result must be funded, declined, or pending"})
        conn = db.get_conn()
        org = conn.execute("SELECT id FROM organizations WHERE id=? AND user_id=?", (org_id, user_id)).fetchone()
        if not org:
            conn.close()
            return json_response(self, 404, {"error": "org not found"})
        score_at_time = data.get("scoreAtTime")
        if score_at_time is None:
            latest = conn.execute(
                "SELECT overall FROM readiness_scores WHERE org_id=? ORDER BY computed_at DESC LIMIT 1", (org_id,)
            ).fetchone()
            score_at_time = latest["overall"] if latest else None
        conn.execute(
            "INSERT INTO outcomes (org_id, funder_name, result, amount, score_at_time, notes, logged_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (org_id, data["funderName"], data["result"], data.get("amount"), score_at_time, data.get("notes"), db.now()),
        )
        conn.commit()
        conn.close()
        return json_response(self, 201, {"saved": True})

    def _list_outcomes(self, org_id):
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        conn = db.get_conn()
        org = conn.execute("SELECT id FROM organizations WHERE id=? AND user_id=?", (org_id, user_id)).fetchone()
        if not org:
            conn.close()
            return json_response(self, 404, {"error": "org not found"})
        rows = conn.execute(
            "SELECT * FROM outcomes WHERE org_id=? ORDER BY logged_at DESC", (org_id,)
        ).fetchall()
        conn.close()
        return json_response(self, 200, {"outcomes": [dict(r) for r in rows]})

    # ---------- full-account export (backup, given the free-tier disk isn't persistent) ----------
    def _export_account(self):
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        conn = db.get_conn()
        orgs = conn.execute("SELECT * FROM organizations WHERE user_id=?", (user_id,)).fetchall()
        export = {"exportedAt": db.now(), "organizations": []}
        for org in orgs:
            org_id = org["id"]
            snapshots = conn.execute(
                "SELECT * FROM financial_snapshots WHERE org_id=? ORDER BY ingested_at", (org_id,)
            ).fetchall()
            manual = conn.execute(
                "SELECT * FROM manual_dimensions WHERE org_id=?", (org_id,)
            ).fetchone()
            scores = conn.execute(
                "SELECT * FROM readiness_scores WHERE org_id=? ORDER BY computed_at", (org_id,)
            ).fetchall()
            reports = conn.execute(
                "SELECT * FROM report_entries WHERE org_id=? ORDER BY created_at", (org_id,)
            ).fetchall()
            outcomes = conn.execute(
                "SELECT * FROM outcomes WHERE org_id=? ORDER BY logged_at", (org_id,)
            ).fetchall()
            export["organizations"].append({
                "org": dict(org),
                "financialSnapshots": [dict(r) for r in snapshots],
                "manualDimensions": dict(manual) if manual else None,
                "scoreHistory": [dict(r) for r in scores],
                "reports": [dict(r) for r in reports],
                "outcomes": [dict(r) for r in outcomes],
            })
        funders = conn.execute("SELECT * FROM funders WHERE user_id=?", (user_id,)).fetchall()
        export["funders"] = [dict(r) for r in funders]
        conn.close()
        return json_response(self, 200, export)

    # ---------- funders ----------
    def _create_funder(self):
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        data = self._read_json()
        if not data.get("name") or not data.get("weights"):
            return json_response(self, 400, {"error": "name and weights required"})
        conn = db.get_conn()
        cur = conn.execute(
            "INSERT INTO funders (user_id, name, focus, grant_range, approach, weights_json, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                user_id, data["name"], data.get("focus"), data.get("grantRange"), data.get("approach"),
                json.dumps(data["weights"]), db.now(),
            ),
        )
        conn.commit()
        funder_id = cur.lastrowid
        conn.close()
        return json_response(self, 201, {"id": funder_id})

    def _list_funders(self):
        conn = db.get_conn()
        rows = conn.execute("SELECT * FROM funders").fetchall()
        conn.close()
        out = []
        for r in rows:
            d = dict(r)
            d["weights"] = json.loads(d.pop("weights_json") or "{}")
            out.append(d)
        return json_response(self, 200, {"funders": out})

    def _rank_for_funder(self, funder_id):
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        conn = db.get_conn()
        funder = conn.execute("SELECT * FROM funders WHERE id=?", (funder_id,)).fetchone()
        if not funder:
            conn.close()
            return json_response(self, 404, {"error": "funder not found"})
        weights = json.loads(funder["weights_json"] or "{}")
        orgs = conn.execute("SELECT id, name FROM organizations WHERE user_id=?", (user_id,)).fetchall()

        results = []
        for org in orgs:
            scored = score_org(conn, org["id"])
            total_w = sum(weights.values()) or 1
            weighted = 0.0
            for dim_name, w in weights.items():
                key = scoring.NAME_TO_KEY.get(dim_name)
                if key:
                    weighted += scored["dimensionScores"].get(key, 50) * w
            results.append({
                "orgId": org["id"],
                "orgName": org["name"],
                "readinessScore": scored["overall"],
                "weightedScore": round(weighted / total_w, 1),
            })
        conn.close()
        results.sort(key=lambda r: r["weightedScore"], reverse=True)
        return json_response(self, 200, {"funder": funder["name"], "ranking": results})

    # ---------- donor sustainability (fed by the standalone Google Form) ----------
    def _ingest_donor_sustainability(self):
        """Webhook target for the Apps Script onFormSubmit trigger on the
        'Donor Sustainability & Stewardship Assessment' form. Protected by a
        shared secret (X-Ingest-Secret header), not user Bearer auth, since
        there's no logged-in GrantPass session behind a form submission.

        Body:
        {
          "orgName": str, "respondentRole": str?,
          "ratings": {"grassrootsCultivation": 1-5, "stewardshipInfrastructure": 1-5,
                       "engagementCadence": 1-5, "firstGiftFollowThrough": 1-5,
                       "ownershipClarity": 1-5, "boardReadiness": 1-5,
                       "donorDataMaturity": 1-5, "earlyWarningCapacity": 1-5},
          "evidence": {<same 8 keys>: str}, "finalNotes": str?,
          "formResponseId": str?, "submittedAt": str? (ISO)
        }"""
        if not check_ingest_secret(self):
            return json_response(self, 401, {"error": "invalid or missing ingest secret"})
        data = self._read_json()
        ratings = data.get("ratings") or {}
        keys = [
            "grassrootsCultivation", "stewardshipInfrastructure", "engagementCadence",
            "firstGiftFollowThrough", "ownershipClarity", "boardReadiness",
            "donorDataMaturity", "earlyWarningCapacity",
        ]
        col_for_key = {
            "grassrootsCultivation": "grassroots_cultivation",
            "stewardshipInfrastructure": "stewardship_infrastructure",
            "engagementCadence": "engagement_cadence",
            "firstGiftFollowThrough": "first_gift_follow_through",
            "ownershipClarity": "ownership_clarity",
            "boardReadiness": "board_readiness",
            "donorDataMaturity": "donor_data_maturity",
            "earlyWarningCapacity": "early_warning_capacity",
        }
        present = [ratings[k] for k in keys if isinstance(ratings.get(k), (int, float))]
        avg_score = round(((sum(present) / len(present)) - 1) / 4 * 100, 1) if present else None

        conn = db.get_conn()
        org_id = None
        org_name = (data.get("orgName") or "").strip()
        if org_name:
            match = conn.execute(
                "SELECT id FROM organizations WHERE lower(name)=lower(?) LIMIT 1", (org_name,)
            ).fetchone()
            if match:
                org_id = match["id"]
        cur = conn.execute(
            """INSERT INTO donor_sustainability_responses
               (org_id, org_name, respondent_role, grassroots_cultivation, stewardship_infrastructure,
                engagement_cadence, first_gift_follow_through, ownership_clarity, board_readiness,
                donor_data_maturity, early_warning_capacity, average_score, evidence_json, final_notes,
                form_response_id, submitted_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                org_id, org_name or None, data.get("respondentRole"),
                ratings.get("grassrootsCultivation"), ratings.get("stewardshipInfrastructure"),
                ratings.get("engagementCadence"), ratings.get("firstGiftFollowThrough"),
                ratings.get("ownershipClarity"), ratings.get("boardReadiness"),
                ratings.get("donorDataMaturity"), ratings.get("earlyWarningCapacity"),
                avg_score, json.dumps(data.get("evidence") or {}), data.get("finalNotes"),
                data.get("formResponseId"), data.get("submittedAt") or db.now(),
            ),
        )
        conn.commit()
        response_id = cur.lastrowid
        conn.close()
        return json_response(self, 201, {"saved": True, "id": response_id, "orgId": org_id, "averageScore": avg_score})

    def _list_donor_sustainability(self):
        """Requires normal user Bearer auth (this is personal data once
        read back), unlike the ingest endpoint. Optional ?org=<substring>
        filter on org_name for convenience."""
        user_id = get_auth_user(self)
        if not user_id:
            return json_response(self, 401, {"error": "auth required"})
        query = urlparse(self.path).query
        org_filter = None
        for part in query.split("&"):
            if part.startswith("org="):
                from urllib.parse import unquote_plus
                org_filter = unquote_plus(part[4:])
        conn = db.get_conn()
        if org_filter:
            rows = conn.execute(
                "SELECT * FROM donor_sustainability_responses WHERE org_name LIKE ? ORDER BY submitted_at DESC",
                (f"%{org_filter}%",),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM donor_sustainability_responses ORDER BY submitted_at DESC"
            ).fetchall()
        conn.close()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["evidence"] = json.loads(d.pop("evidence_json") or "{}")
            except Exception:
                d["evidence"] = {}
            out.append(d)
        return json_response(self, 200, {"responses": out})


def main():
    port = int(os.environ.get("PORT", 8420))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"GrantPass backend listening on http://0.0.0.0:{port}  (db: {db.DB_PATH})")
    server.serve_forever()


if __name__ == "__main__":
    main()