"""Sends free-scorecard leads (a visitor who leaves an email after their
result) into the Frankly Inspired Operating System's Prospecting view, and
emails the visitor their result through the website backend's existing
mail setup.

Environment variables (all optional; anything missing just skips that step):
  OS_API_URL          e.g. https://frankly-inspired-os.onrender.com
  OS_PROSPECTS_TOKEN  the operations app's prospects-scoped admin key
Never raises: a failure here must never break the visitor's request.
"""
import json
import os
import urllib.request

OS_API_URL = (os.environ.get("OS_API_URL") or "").rstrip("/")
OS_PROSPECTS_TOKEN = os.environ.get("OS_PROSPECTS_TOKEN") or ""

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
