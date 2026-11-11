"""Sends free-scorecard leads (a visitor who leaves an email after their
result) into the Frankly Inspired Operating System's Prospecting view, and
emails the visitor their result through the website backend's existing
mail setup.

Environment variables (all optional; anything missing just skips that step):
  OS_API_URL             e.g. https://frankly-inspired-os.onrender.com
  OS_PROSPECTS_TOKEN     the operations app's prospects-scoped admin key
  WEBSITE_API_URL        e.g. https://frankly-inspired-api.onrender.com
  SCORECARD_MAIL_SECRET  shared with the website backend; lets it email results
Never raises: a failure here must never break the visitor's request.
"""
import json
import os
import urllib.request

OS_API_URL = (os.environ.get("OS_API_URL") or "").rstrip("/")
OS_PROSPECTS_TOKEN = os.environ.get("OS_PROSPECTS_TOKEN") or ""
WEBSITE_API_URL = (os.environ.get("WEBSITE_API_URL") or "").rstrip("/")
SCORECARD_MAIL_SECRET = os.environ.get("SCORECARD_MAIL_SECRET") or ""

STAGE_NAMES = {"BUILD": "Formation Readiness", "FUND": "Grant Readiness", "SUSTAIN": "Institutional Durability"}


def build_notes(row):
    """Plain-text notes for the prospect record, from a demo_score_log row."""
    stage = row.get("stage") or ""
    lines = [
        f"Free InstitutionalOS Scorecard: {STAGE_NAMES.get(stage, stage)} stage",
        f"Overall Health Index: {round(row.get('overall') or 0)}/100 (self-described, unverified)",
    ]
    try:
        dims = json.loads(row.get("dimensions_json") or "[]")
    except ValueError:
        dims = []
    if dims:
        lines.append("By dimension:")
        for d in dims:
            lines.append(f"- {d.get('name')}: {round(d.get('score') or 0)}")
        lowest = min(dims, key=lambda d: d.get("score") or 0)
        lines.append(f"Lowest dimension (likely constraint): {lowest.get('name')}")
    return "\n".join(lines)


DIM_KEYS = {
    "Strategy and Positioning": "strategy", "Program and Impact Evidence": "program",
    "Revenue and Financial Health": "revenue", "Leadership and Organizational Capacity": "leadership",
    "Operations and Infrastructure": "operations", "Partnerships and Ecosystem": "partnerships",
    "Governance and Risk": "governance",
}


def self_scores(row):
    """{dimension key: score} from a scorecard row, using the website's
    dimension keys (revenue, not financial), so FIOS and the console can
    compare a client's self-assessment with the verified Diagnostic."""
    try:
        dims = json.loads(row.get("dimensions_json") or "[]")
    except ValueError:
        return {}
    out = {}
    for d in dims:
        k = DIM_KEYS.get(d.get("name"))
        if k and isinstance(d.get("score"), (int, float)):
            out[k] = round(float(d["score"]))
    return out


def push_prospect(row, email):
    if not (OS_API_URL and OS_PROSPECTS_TOKEN):
        return False
    item = {
        "name": row.get("org_name") or email,
        "org": row.get("org_name") or "",
        "source": "institutionalos scorecard",
        "status": "new",
        "link": "",
        "notes": f"Email: {email}\n" + build_notes(row),
        "sourceRef": f"scorecard-{row.get('id')}",
        "selfScores": self_scores(row),
    }
    req = urllib.request.Request(
        OS_API_URL + "/api/admin/prospects",
        data=json.dumps({"items": [item]}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Admin-Token": OS_PROSPECTS_TOKEN},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as res:
            body = json.loads(res.read().decode("utf-8") or "{}")
            return bool(body.get("ok"))
    except Exception as exc:  # noqa: BLE001 - best effort by design
        print(f"os_sync.push_prospect failed: {exc}")
        return False


def send_results_email(row, email, os_added, band=None, decision=None, continue_url=None):
    """Asks the website backend to email the visitor their result (and
    notify Franklin). Returns True if the visitor's email was accepted."""
    if not (WEBSITE_API_URL and SCORECARD_MAIL_SECRET):
        return False
    try:
        dims = json.loads(row.get("dimensions_json") or "[]")
    except ValueError:
        dims = []
    stage = row.get("stage") or ""
    payload = {
        "email": email,
        "stage": stage,
        "stageName": STAGE_NAMES.get(stage, stage),
        "overall": float(row.get("overall") or 0),
        "band": band or "",
        "decision": decision or "",
        "orgName": row.get("org_name") or "",
        "continueUrl": continue_url or "",
        "leadRef": f"scorecard-{row.get('id')}",
        "osAdded": bool(os_added),
        "dimensions": [
            {"name": d.get("name"), "score": d.get("score"), "note": d.get("note"), "liftTarget": d.get("liftTarget")}
            for d in dims
        ],
    }
    req = urllib.request.Request(
        WEBSITE_API_URL + "/api/scorecard-results",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Scorecard-Secret": SCORECARD_MAIL_SECRET},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            body = json.loads(res.read().decode("utf-8") or "{}")
            return bool(body.get("emailed"))
    except Exception as exc:  # noqa: BLE001 - best effort by design
        print(f"os_sync.send_results_email failed: {exc}")
        return False


# ---------- Diagnostic results back to FIOS ----------
# When a client in the console is linked to a FIOS pipeline deal
# (organizations.external_ref = the deal id), every save of its Diagnostic
# record, portal details, or score pushes a summary to FIOS, which updates
# the deal and its Problem Log entry. Needs OS_API_URL and OS_IOS_TOKEN (the
# operations app's ios-scoped admin key). Runs in a background thread so a
# cold FIOS never slows the console.
OS_IOS_TOKEN = os.environ.get("OS_IOS_TOKEN") or ""


def push_diagnostic(summary):
    if not (OS_API_URL and OS_IOS_TOKEN and summary.get("externalRef")):
        return False
    import threading

    def send():
        req = urllib.request.Request(
            OS_API_URL + "/api/admin/ios-sync",
            data=json.dumps(summary).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Admin-Token": OS_IOS_TOKEN},
            method="POST",
        )
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=45) as res:
                    res.read()
                    return
            except Exception as exc:  # noqa: BLE001 - best effort; the daily reconciliation catches misses
                print(f"os_sync.push_diagnostic attempt {attempt + 1} failed: {exc}")

    threading.Thread(target=send, daemon=True).start()
    return True
