"""
Real IRS Form 990 e-file XML parser (stdlib xml.etree only).

The IRS publishes e-filed 990s as XML using the schema at
https://www.irs.gov/e-file-providers/exempt-organizations-e-file-search-990-filings
Field names vary slightly across 990 / 990-EZ / 990-PF and schema versions
(e.g. CYTotalRevenueAmt vs TotalRevenueAmt), so this parser is tolerant: it
flattens the whole document by local tag name (namespace stripped) and looks
up each field through a list of known aliases, in priority order.

This is real, runnable parsing logic - see sample_990.xml for a fixture you
can test it against right now. It has NOT been run against a live IRS filing
in this environment because this sandbox currently has no outbound network
access (see README "What's real vs. stubbed"). Once you deploy this
somewhere with network access, fetch_990.py shows how to pull real filings
by EIN and pipe them straight into this parser.
"""
import xml.etree.ElementTree as ET

FIELD_ALIASES = {
    "ein": ["EIN"],
    "org_name": ["BusinessNameLine1Txt", "BusinessNameLine1"],
    "tax_year": ["TaxYr", "TaxYear"],
    "total_revenue": ["CYTotalRevenueAmt", "TotalRevenueAmt", "TotalRevenueCurrentYear"],
    "total_expenses": ["CYTotalExpensesAmt", "TotalExpensesAmt", "TotalExpensesCurrentYear"],
    "total_assets": ["TotalAssetsEOYAmt", "TotalAssetsGrpEOYAmt"],
    "net_assets": ["NetAssetsOrFundBalancesEOYAmt", "TotalNetAssetsFundBalanceEOYAmt"],
    "contributions_revenue": ["CYContributionsGrantsAmt", "TotalContributionsAmt"],
    "program_revenue": ["CYProgramServiceRevenueAmt", "TotalProgramServiceRevenueAmt"],
}

NUMERIC_FIELDS = [
    "total_revenue", "total_expenses", "total_assets",
    "net_assets", "contributions_revenue", "program_revenue",
]


def _strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _flatten(root) -> dict:
    """First occurrence of each local tag name -> its text content."""
    values = {}
    for elem in root.iter():
        tag = _strip_ns(elem.tag)
        text = (elem.text or "").strip()
        if text and tag not in values:
            values[tag] = text
    return values


def parse_990_xml(xml_bytes: bytes) -> dict:
    if not xml_bytes:
        raise ValueError("empty XML payload")
    root = ET.fromstring(xml_bytes)
    flat = _flatten(root)

    result = {}
    for key, aliases in FIELD_ALIASES.items():
        val = None
        for alias in aliases:
            if alias in flat:
                val = flat[alias]
                break
        result[key] = val

    for key in NUMERIC_FIELDS:
        raw = result.get(key)
        if raw is None:
            continue
        try:
            result[key] = float(raw)
        except ValueError:
            result[key] = None

    return result
