#!/usr/bin/env python3
"""Automated tests for InstitutionalOS. Starts the real server against a
throwaway Postgres database and exercises sign-in, clients, scoring, the
90-Day Improvement Plan, the client portal, one sign-in from the operations
app, and the backup. Run before every deploy:

    TEST_DATABASE_URL=postgres://postgres@localhost:5432/ios_test python3 tests/run_tests.py

The database is emptied first, so never point this at real data."""
import json, os, random, subprocess, sys, time, urllib.request, urllib.error
import psycopg2

DB = os.environ.get("TEST_DATABASE_URL")
if not DB:
    sys.exit("Set TEST_DATABASE_URL to an empty test database.")
PORT = random.randint(7000, 7900)
BASE = f"http://localhost:{PORT}"
passed = failed = 0

def call(method, path, body=None, token=None, headers=None):
    h = {"Content-Type": "application/json"}
    if token: h["Authorization"] = "Bearer " + token
    h.update(headers or {})
    req = urllib.request.Request(BASE + path, method=method, headers=h, data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b"{}")
        except Exception: return e.code, {}

def t(name, fn):
    global passed, failed
    try:
        fn(); passed += 1; print("  ok   " + name)
    except Exception as e:
        failed += 1; print("  FAIL " + name + "\n       " + repr(e))

conn = psycopg2.connect(DB); conn.autocommit = True
conn.cursor().execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"); conn.close()
env = dict(os.environ, PORT=str(PORT), DATABASE_URL=DB, INTEGRATION_KEY="ik-test", INTEGRATION_USER_EMAIL="owner@test.org", OS_IOS_TOKEN="")
srv = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "..", "server.py")], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
for _ in range(80):
    try:
        urllib.request.urlopen(BASE + "/health", timeout=1); break
    except Exception:
        time.sleep(0.25)

S = {}
print("InstitutionalOS tests")
def register():
    st, d = call("POST", "/auth/register", {"email": "owner@test.org", "password": "password-123"})
    assert st in (200, 201) and d.get("token"), (st, d)
    st, d = call("POST", "/auth/login", {"email": "owner@test.org", "password": "password-123"})
    assert st == 200; S["token"] = d["token"]
t("accounts: register and sign in", register)
t("accounts: wrong password refused", lambda: (lambda r: (_ for _ in ()).throw(AssertionError(r)) if r[0] == 200 else None)(call("POST", "/auth/login", {"email": "owner@test.org", "password": "nope"})))
t("clients: unauthenticated list refused", lambda: (lambda r: None if r[0] == 401 else (_ for _ in ()).throw(AssertionError(r)))(call("GET", "/orgs")))
def create_org():
    st, d = call("POST", "/orgs", {"name": "Test Youth Alliance", "stage": "FUND"}, S["token"])
    assert st in (200, 201) and d.get("id"), (st, d); S["org"] = d["id"]
t("clients: create an organization", create_org)
def score():
    dims = {k: 50 for k in ["strategy", "program", "leadership", "operations", "partnerships", "governance"]}
    st, d = call("POST", f"/orgs/{S['org']}/dimensions", dims, S["token"])
    assert st == 200, (st, d)
    st, d = call("GET", f"/orgs/{S['org']}/score", token=S["token"])
    assert st == 200, (st, d)
t("scores: save dimensions and read the score", score)
def plan():
    st, d = call("POST", f"/orgs/{S['org']}/plan", {"startDate": time.strftime("%Y-%m-%d"), "target": "Close the revenue gap", "dimension": "financial"}, S["token"])
    assert st == 200, (st, d)
    st, d = call("POST", f"/orgs/{S['org']}/plan/actions", {"title": "Draft a reserve policy", "owner": "ED", "dueDate": time.strftime("%Y-%m-%d")}, S["token"])
    assert st == 200, (st, d)
    st, d = call("GET", f"/orgs/{S['org']}/plan", token=S["token"])
    assert st == 200 and (d.get("actions") or d.get("plan")), (st, d)
t("plan: 90-Day Improvement Plan with an action", plan)
def portal():
    st, d = call("POST", f"/orgs/{S['org']}/portal", {}, S["token"])
    assert st == 200, (st, d)
t("portal: client portal link can be created", portal)
def evidence():
    st, d = call("POST", f"/orgs/{S['org']}/dimensions", {"scores": {"strategy": 70}, "evidence": {"strategy": {"note": "Board-approved plan", "source": "https://example.org/plan"}}}, S["token"])
    assert st == 200, (st, d)
    st, d = call("POST", f"/orgs/{S['org']}/plan/reviews", {"kind": "weekly", "reviewDate": time.strftime("%Y-%m-%d"), "evidenceAdded": "Reserve policy draft"}, S["token"])
    assert st == 200, (st, d)
    st, link = call("POST", f"/orgs/{S['org']}/client-link", {}, S["token"])
    assert st == 200 and link.get("clientToken"), (st, link)
    st, p = call("GET", "/public/portal/" + link["clientToken"])
    assert st == 200 and p["evidence"]["dimensions"]["strategy"]["source"] == "https://example.org/plan", p.get("evidence")
    assert any(x["text"] == "Reserve policy draft" for x in p["evidence"]["log"]), p["evidence"]["log"]
    st, sh = call("POST", f"/orgs/{S['org']}/share", {}, S["token"])
    tok = sh.get("token") or sh.get("shareToken") or sh.get("share_token")
    if tok:
        st, r = call("GET", "/public/report/" + tok)
        assert "evidence" not in r, "funder share link must not include evidence notes"
t("portal: evidence on file and the evidence log reach the client portal only", evidence)
def comparison():
    # A baseline score saved before the plan started, then today's score is higher.
    c = psycopg2.connect(DB); c.autocommit = True; cur = c.cursor()
    dims = json.dumps({"dimensions": [{"name": "Strategy and Positioning", "score": 40}]})
    cur.execute("UPDATE readiness_scores SET computed_at = '2000-01-01T00:00:00' WHERE org_id = %s", (S["org"],))
    cur.execute("INSERT INTO readiness_scores (org_id, overall, status, dimensions_json, stage, computed_at) VALUES (%s, 40, 'x', %s, 'FUND', '2000-01-02T00:00:00')", (S["org"], dims))
    c.close()
    st, link = call("POST", f"/orgs/{S['org']}/client-link", {}, S["token"])
    st, p = call("GET", "/public/portal/" + link["clientToken"])
    cmp = p["portal"]["comparison"]
    assert cmp and cmp["baselineDate"] == "2000-01-02", cmp
    row = [x for x in cmp["dimensions"] if x["name"] == "Strategy and Positioning"][0]
    assert row["before"] == 40 and row["after"] == 70 and row["change"] == 30, row
t("portal: before-and-after compares the Diagnostic baseline with today", comparison)
def sso():
    st, d = call("POST", "/integration/session", {}, headers={"X-Integration-Key": "wrong"})
    assert st == 401, (st, d)
    st, d = call("POST", "/integration/session", {}, headers={"X-Integration-Key": "ik-test"})
    assert st == 200 and d.get("token") and d.get("email") == "owner@test.org", (st, d)
    st, orgs = call("GET", "/orgs", token=d["token"])
    assert st == 200 and any(o.get("name") == "Test Youth Alliance" for o in (orgs if isinstance(orgs, list) else orgs.get("organizations", orgs.get("orgs", [])))), (st, orgs)
t("one sign-in: integration session works as the console user", sso)
def growth_stage_and_score():
    st, d = call("GET", f"/orgs/{S['org']}/growth", token=S["token"])
    assert st == 200 and "inputs" in d, (st, d)
    st, d = call("POST", f"/orgs/{S['org']}/growth", {"inputs": {"budget": 750000, "staff_fte": 6, "reserve_months": 2,
        "personnel_share": 62, "largest_source_share": 45, "board_size": 6, "board_giving_pct": 80, "ed_evaluated": False,
        "filled_seats": ["ed_full_time", "program_manager"], "policies": ["bylaws", "conflict_of_interest"]}}, S["token"])
    assert st == 200, (st, d)
    g = d["growth"]
    assert g["stage"] == 2 and g["stageName"] == "Emerging", g
    assert g["outOf"] == 20 and 0 <= g["score"] <= 20 and len(g["pillars"]) == 5, g
    assert [h["seat"] for h in g["nextHires"]] == ["development_coordinator", "operations_coordinator"], g["nextHires"]
    h = g["nextHires"][0]
    assert h["loadedCost"] == 65000 and h["budgetRequired"] == 100000, h
    assert any("100% board giving" in x for x in g["board"]["gaps"]) and any("Whistleblower" in x for x in g["board"]["gaps"]), g["board"]
    assert g["baseline"]["score"] == g["score"] and len(g["history"]) == 1, g
    S["growth_first"] = g["score"]
t("growth: stage, readiness score, next hires and board gaps", growth_stage_and_score)
def growth_progress():
    st, d = call("POST", f"/orgs/{S['org']}/growth", {"inputs": {"reserve_months": 4, "board_giving_pct": 100, "ed_evaluated": True, "staff_fte": None}}, S["token"])
    g = d["growth"]
    assert st == 200 and g["score"] > S["growth_first"] and len(g["history"]) == 2, (st, g)
    assert g["baseline"]["score"] == S["growth_first"], g["baseline"]
    assert "staff_fte" not in d["inputs"] and d["inputs"]["budget"] == 750000, d["inputs"]
    assert call("POST", f"/orgs/{S['org']}/growth", {"inputs": {"bogus": 1}}, S["token"])[0] == 400
    assert call("GET", f"/orgs/{S['org']}/growth")[0] == 401
    st, r = call("GET", f"/orgs/{S['org']}/full-report", token=S["token"])
    assert st == 200 and r["growth"]["stage"] == 2, (st, r.get("growth"))
    st, c = call("GET", "/growth/catalog")
    assert st == 200 and len(c["stages"]) == 5 and any(x["key"] == "development_director" for x in c["seats"]), st
t("growth: re-assessment shows progress against the baseline", growth_progress)
def case_study():
    st, d = call("GET", f"/orgs/{S['org']}/case-study", token=S["token"])
    assert st == 200 and d["markdown"].startswith("# Case study: Test Youth Alliance"), (st, d)
    assert "Stage Readiness Score:" in d["markdown"] and d["hasGrowthMovement"], d["markdown"]
    assert "[Quote from the 90-day results interview.]" in d["markdown"]
    assert call("GET", f"/orgs/{S['org']}/case-study")[0] == 401
t("case study: a draft from scores, growth movement and the plan", case_study)
def legacy_readiness():
    st, d = call("GET", f"/orgs/{S['org']}/legacy", token=S["token"])
    assert st == 200 and d["legacy"]["total"] == 6 and len(d["markers"]) == 6, (st, d)
    st, d = call("POST", f"/orgs/{S['org']}/legacy", {"markers": {"deputy": True, "decisions": True, "succession": False, "concentration": True}}, S["token"])
    lg = d["legacy"]
    assert st == 200 and lg["met"] >= 3 and len(lg["history"]) == 1, (st, lg)
    assert {x["key"]: x["met"] for x in lg["items"]}["succession"] is False
    assert call("POST", f"/orgs/{S['org']}/legacy", {"markers": {"bogus": True}}, S["token"])[0] == 400
    assert call("GET", f"/orgs/{S['org']}/legacy")[0] == 401
    st, r = call("GET", f"/orgs/{S['org']}/full-report", token=S["token"])
    assert st == 200 and r["legacy"]["met"] == lg["met"] and r["gapFirst"] and r["gapFirst"]["why"] in ("below-minimum", "weighted"), (st, r.get("gapFirst"))
t("legacy: six markers, history, and the gap rule in the report", legacy_readiness)
def scoring_model_published():
    st, d = call("GET", "/scoring-model")
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); import scoring
    assert st == 200 and d == scoring.scoring_model(), (st, d)
    assert set(d["stages"]) == {"BUILD", "FUND", "SUSTAIN"} and len(d["legacyMarkers"]) == 6
    for stage in d["stages"].values():
        assert sum(stage["weights"].values()) == 100, stage
t("scoring model: published without sign-in, weights add to 100 on every path", scoring_model_published)
def validation_record():
    import psycopg2 as pg
    c = pg.connect(DB); c.autocommit = True
    c.cursor().execute("UPDATE organizations SET self_scores=%s WHERE id=%s", (json.dumps({"strategy": 90, "governance": 80, "leadership": 85}), S["org"]))
    c.close()
    st, d = call("POST", f"/orgs/{S['org']}/milestones", {"kind": "expansion_opened", "note": "Second site", "happenedOn": "2026-11-20"}, S["token"])
    assert st == 200 and d["milestones"][-1]["overall"] is not None, (st, d)
    assert call("POST", f"/orgs/{S['org']}/milestones", {"kind": "nope"}, S["token"])[0] == 400
    st, v = call("GET", "/validation", token=S["token"])
    assert st == 200 and v["clientsWithBoth"] >= 1 and "strategy" in v["byDimension"], (st, v)
    assert v["byDimension"]["strategy"]["avgSelfMinusVerified"] > 0, v["byDimension"]
    assert v["outcomes"]["logged"] >= 1 and v["enoughData"] is False
    assert call("GET", "/validation")[0] == 401
t("validation: self vs verified across clients, and outcomes with the score at the time", validation_record)
def backup():
    st, d = call("GET", "/integration/backup", headers={"X-Integration-Key": "ik-test"})
    assert st == 200 and "organizations" in d["tables"] and len(d["tables"]["organizations"]) == 1, (st, list(d.get("tables", {}))[:5])
    assert call("GET", "/integration/backup")[0] == 401
t("backup: full export with the integration key only", backup)

srv.terminate()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
