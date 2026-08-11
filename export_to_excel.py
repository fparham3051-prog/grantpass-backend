"""
Exports every organization in your GrantPass backend into an Excel workbook
shaped exactly like the Portfolio Scorecard template (same shared builder,
portfolio_sheet.py) — the DB-to-Excel counterpart to bulk_ingest.py's
CSV-to-DB direction. Pulls each org's latest financial snapshot and its
current readiness score (all 8 dimensions) via the backend's own API, so it
only ever reads what a normal API client could read.

Usage:
    python3 export_to_excel.py --token <your-auth-token> --output portfolio.xlsx

Writes to a scratch path first and only touches the final --output path once
at the very end (see README) - repeatedly overwriting an .xlsx in place on
some mounted/synced folders corrupts the file silently.
"""
import argparse
import json
import shutil
import sys
import tempfile
import urllib.error
import urllib.request

import openpyxl

from portfolio_sheet import add_portfolio_scorecard_sheet, MANUAL_KEYS


def http_json(method: str, url: str, token: str = None):
    req = urllib.request.Request(url, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {"error": "unreadable error response"}


def fetch_org_row(api_url: str, token: str, org: dict) -> dict:
    org_id = org["id"]

    status, snap_body = http_json("GET", f"{api_url}/orgs/{org_id}/financial-snapshot", token)
    snapshot = snap_body.get("snapshot") if status == 200 else None

    status, score_body = http_json("GET", f"{api_url}/orgs/{org_id}/score", token)
    if status != 200:
        raise RuntimeError(f"could not fetch score for org {org_id}: {score_body}")

    dims_by_name = {d["name"]: d["score"] for d in score_body.get("dimensions", [])}
    name_to_key = {
        "Legal & Compliance": "legal", "Governance": "governance", "Strategic Clarity": "strategy",
        "Track Record": "trackRecord", "Outcome Measurement": "outcomes",
        "Leadership Stability": "leadership", "Reporting Capacity": "reporting",
    }
    manual_scores = {key: dims_by_name.get(dim_name, 50) for dim_name, key in name_to_key.items()}

    row = {
        "name": org["name"],
        "ein": org.get("ein") or "",
        "total_revenue": snapshot.get("total_revenue") if snapshot else None,
        "total_expenses": snapshot.get("total_expenses") if snapshot else None,
        "total_assets": snapshot.get("total_assets") if snapshot else None,
        "net_assets": snapshot.get("net_assets") if snapshot else None,
        "contributions_revenue": snapshot.get("contributions_revenue") if snapshot else None,
        "program_revenue": snapshot.get("program_revenue") if snapshot else None,
        **manual_scores,
    }
    if not snapshot:
        row["note"] = "No financial data ingested yet (ingest-990 / ingest-financial-data / bulk_ingest.py) — revenue fields default to 0."
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api-url", default="http://localhost:8420")
    ap.add_argument("--token", required=True)
    ap.add_argument("--output", default="portfolio-export.xlsx")
    args = ap.parse_args()

    status, body = http_json("GET", f"{args.api_url}/orgs", args.token)
    if status != 200:
        print(f"Could not list organizations: {body}", file=sys.stderr)
        sys.exit(1)
    orgs = body.get("organizations", [])
    if not orgs:
        print("No organizations found for this account yet — nothing to export.")
        sys.exit(0)

    print(f"Exporting {len(orgs)} organization(s) from {args.api_url} ...")
    rows = []
    for org in orgs:
        try:
            row = fetch_org_row(args.api_url, args.token, org)
            rows.append(row)
            print(f"  - {row['name']}: fetched")
        except Exception as e:
            print(f"  - {org.get('name', org.get('id'))}: FAILED — {e}", file=sys.stderr)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    add_portfolio_scorecard_sheet(
        wb, rows,
        subtitle=(f"Live export from {args.api_url} — {len(rows)} organization(s). Blue cells are "
                  "raw data as of export time; edit and the formulas recalculate, but re-running "
                  "this script will overwrite manual edits with fresh backend data."),
        blank_rows=5,
    )

    # Write to a scratch temp file first, then move into place in one step -
    # avoids the in-place-overwrite corruption issue noted in the README.
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = f"{tmpdir}/export.xlsx"
        wb.save(tmp_path)
        shutil.copyfile(tmp_path, args.output)

    print(f"\nDone. Wrote {args.output} ({len(rows)} organization(s)).")
    print("Formulas are unevaluated until opened in Excel/LibreOffice and recalculated "
          "(or run scripts/recalc.py from the xlsx skill if you have it available).")


if __name__ == "__main__":
    main()
