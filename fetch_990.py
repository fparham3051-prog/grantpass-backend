"""
Real-world 990 fetching, for once this backend runs somewhere with outbound
network access (this sandbox currently has none - see README).

ProPublica's Nonprofit Explorer API is free, public, and requires no API key:
    https://projects.propublica.org/nonprofits/api/v2/organizations/{ein}.json
It returns each filing's summary financials directly as JSON (no XML parsing
needed for that data). For the full e-filed XML (needed for fields not in the
ProPublica summary), the IRS publishes raw 990 XML in a public AWS Open Data
bucket: https://registry.opendata.aws/irs990/

This script is written against the real, documented ProPublica API shape.
It has NOT been executed in this environment (no network access here), so
treat the exact JSON key paths as "correct per the public API docs, verify
once you run this with real connectivity."

Usage once deployed somewhere with network access:
    python3 fetch_990.py 133556677 > filing.json

For loading more than one organization at a time, see bulk_ingest.py, which
imports fetch_propublica() and to_financial_snapshot() from this module and
posts the result straight to POST /orgs/{id}/ingest-financial-data.
"""
import json
import sys
import urllib.request

PROPUBLICA_URL = "https://projects.propublica.org/nonprofits/api/v2/organizations/{ein}.json"


def fetch_propublica(ein: str) -> dict:
    url = PROPUBLICA_URL.format(ein=ein.strip())
    req = urllib.request.Request(url, headers={"User-Agent": "GrantPass/0.1 (prototype)"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def to_financial_snapshot(propublica_json: dict) -> dict:
    """Map ProPublica's response shape to the exact fields
    POST /orgs/{id}/ingest-financial-data expects (see server.py). ProPublica
    returns `filings_with_data`, most recent first, each with
    totrevenue / totfuncexpns / totassetsend / totliabend etc."""
    filings = propublica_json.get("filings_with_data") or []
    if not filings:
        raise ValueError("no filings returned for this EIN")
    latest = filings[0]
    total_assets = latest.get("totassetsend")
    total_liabilities = latest.get("totliabend")
    net_assets = None
    if total_assets is not None and total_liabilities is not None:
        net_assets = total_assets - total_liabilities

    return {
        "source": "propublica",
        "fiscal_year": latest.get("tax_prd_yr"),
        "total_revenue": latest.get("totrevenue"),
        "total_expenses": latest.get("totfuncexpns"),
        "total_assets": total_assets,
        "net_assets": net_assets,
        "contributions_revenue": latest.get("totcntrbgfts"),
        "program_revenue": latest.get("profitservicerevenue") or latest.get("totprgmrevnue"),
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python3 fetch_990.py <EIN>", file=sys.stderr)
        sys.exit(1)
    data = fetch_propublica(sys.argv[1])
    snapshot = to_financial_snapshot(data)
    print(json.dumps(snapshot, indent=2))
