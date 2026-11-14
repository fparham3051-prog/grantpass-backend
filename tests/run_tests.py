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
def sso():
    st, d = call("POST", "/integration/session", {}, headers={"X-Integration-Key": "wrong"})
    assert st == 401, (st, d)
    st, d = call("POST", "/integration/session", {}, headers={"X-Integration-Key": "ik-test"})
    assert st == 200 and d.get("token") and d.get("email") == "owner@test.org", (st, d)
    st, orgs = call("GET", "/orgs", token=d["token"])
    assert st == 200 and any(o.get("name") == "Test Youth Alliance" for o in (orgs if isinstance(orgs, list) else orgs.get("organizations", orgs.get("orgs", [])))), (st, orgs)
t("one sign-in: integration session works as the console user", sso)
def backup():
    st, d = call("GET", "/integration/backup", headers={"X-Integration-Key": "ik-test"})
    assert st == 200 and "organizations" in d["tables"] and len(d["tables"]["organizations"]) == 1, (st, list(d.get("tables", {}))[:5])
    assert call("GET", "/integration/backup")[0] == 401
t("backup: full export with the integration key only", backup)

srv.terminate()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
