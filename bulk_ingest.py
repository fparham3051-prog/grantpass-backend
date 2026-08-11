"""
Bulk-load financial data for a list of nonprofits into your GrantPass
backend, for free, using ProPublica's public Nonprofit Explorer API (no
API key required) instead of a paid Candid data license.

This is the practical "pre-load my database" answer: give it a CSV of EINs
(the orgs you actually work with, or a target list) and it creates/finds
each organization via the backend's own API and ingests real financial
data for it - the same table and scoring path a single manual ingest uses.

Reuses fetch_propublica() and to_financial_snapshot() from fetch_990.py so
the ProPublica -> snapshot mapping only lives in one place.

TESTED: the CSV parsing, org create/lookup, and POST to
/orgs/{id}/ingest-financial-data were tested end-to-end against a locally
running server (see README "What was actually tested"). The live call to
ProPublica's API (fetch_propublica) has NOT been executed here - this
sandbox has no outbound network access. Run it against 2-3 real EINs first
once you have connectivity, confirm the numbers look right, then point it
at your full list.

Usage:
    python3 bulk_ingest.py --token <your-auth-token> --input eins.csv

Input CSV needs at least an "ein" column; an optional "name" column is used
if the org has to be created (otherwise the name comes from ProPublica):

    ein,name
    133556677,Bright Path Youth Alliance
    042614022,

See sample_eins.csv for a template.
"""
import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request

from fetch_990 import fetch_propublica, to_financial_snapshot


def http_json(method: str, url: str, token: str = None, body: dict = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
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


def get_or_create_org(api_url: str, token: str, name: str, ein: str):
    status, body = http_json("GET", f"{api_url}/orgs", token)
    if status == 200:
        for org in body.get("organizations", []):
            if org.get("ein") == ein:
                return org["id"], False
    status, body = http_json("POST", f"{api_url}/orgs", token, {"name": name, "ein": ein})
    if status != 201:
        raise RuntimeError(f"could not create org: {body}")
    return body["id"], True


def load_one(api_url: str, token: str, ein: str, name_hint: str):
    pp = fetch_propublica(ein)
    org_name = name_hint or (pp.get("organization") or {}).get("name") or f"EIN {ein}"
    org_id, created = get_or_create_org(api_url, token, org_name, ein)

    try:
        snapshot = to_financial_snapshot(pp)
    except ValueError:
        return org_name, org_id, created, None

    status, body = http_json("POST", f"{api_url}/orgs/{org_id}/ingest-financial-data", token, snapshot)
    if status != 200:
        raise RuntimeError(f"ingest failed: {body}")
    return org_name, org_id, created, snapshot


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api-url", default="http://localhost:8420", help="Backend base URL")
    ap.add_argument("--input", required=True, help="CSV file with an 'ein' column")
    ap.add_argument("--token", required=True, help="Auth token from /auth/login or /auth/register")
    ap.add_argument("--delay", type=float, default=0.5, help="Seconds between requests (be polite to the free API)")
    args = ap.parse_args()

    with open(args.input, newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows or "ein" not in rows[0]:
        print("Input CSV must have a header row with at least an 'ein' column.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {len(rows)} organization(s) from {args.input} into {args.api_url} ...")
    loaded, skipped, failed = 0, 0, []

    for i, row in enumerate(rows, 1):
        ein = (row.get("ein") or "").strip()
        name_hint = (row.get("name") or "").strip()
        if not ein:
            continue
        try:
            org_name, org_id, created, snapshot = load_one(args.api_url, args.token, ein, name_hint)
            if snapshot is None:
                skipped += 1
                print(f"[{i}/{len(rows)}] {org_name} (EIN {ein}): no filings on ProPublica, org created but no financial data")
            else:
                loaded += 1
                tag = "new org" if created else "existing org"
                revenue = snapshot.get("total_revenue")
                revenue_str = f"${revenue:,.0f}" if revenue is not None else "unavailable"
                print(f"[{i}/{len(rows)}] {org_name} (EIN {ein}, {tag}): loaded FY{snapshot['fiscal_year']} — revenue {revenue_str}")
        except Exception as e:
            failed.append(ein)
            print(f"[{i}/{len(rows)}] EIN {ein}: FAILED — {e}")
        time.sleep(args.delay)

    print(f"\nDone. {loaded} loaded, {skipped} created with no filing data, {len(failed)} failed.")
    if failed:
        print("Failed EINs:", ", ".join(failed))


if __name__ == "__main__":
    main()
