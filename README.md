# GrantPass Backend

A real backend for the GrantPass readiness-scoring concept: SQLite database,
password-hash auth with signed bearer tokens, a REST API, a real IRS Form 990
XML parser, and deterministic financial scoring — all pure Python 3 standard
library, zero pip installs required.

This was built and **tested end-to-end** (register → login → create org →
ingest a 990 → score → create a funder → rank the pipeline → log a report
entry → auth-rejection checks) in the sandbox this was developed in. See
"What was actually tested" below for the exact run.

## Why stdlib-only

The environment this was built in has no outbound network access at all —
`pip install` fails, no external API can be called. Rather than write
FastAPI/Flask code that was never actually run, this uses only modules that
ship with Python (`http.server`, `sqlite3`, `hashlib`/`hmac`, `xml.etree`) so
every line here has been executed and verified, not just written. It also
means there's nothing to `pip install` and no dependency CVEs to track later
— genuinely simpler, not just a workaround.

## Quickstart

```bash
python3 server.py
# GrantPass backend listening on http://0.0.0.0:8420  (db: ./grantpass.db)
```

No install step. Requires Python 3.10+ (uses `dict | None` type hints in
`scoring.py` — change to `Optional[dict]` if you're on 3.9).

Set `GRANTPASS_SECRET` (token-signing key) and `GRANTPASS_DB` (SQLite file
path) via environment variables in production. The defaults are dev-only.

## API reference

All bodies/responses are JSON unless noted. Protected routes require
`Authorization: Bearer <token>`.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | no | liveness check |
| POST | `/auth/register` | no | `{email, password}` (password 8+ chars) → `{token, userId}` |
| POST | `/auth/login` | no | `{email, password}` → `{token, userId}` |
| POST | `/orgs` | yes | `{name, ein?, description?}` → create an org |
| GET | `/orgs` | yes | list your orgs |
| GET | `/orgs/{id}` | yes | get one org |
| POST | `/orgs/{id}/ingest-990` | yes | body = raw 990 XML bytes → parses and stores a financial snapshot |
| POST | `/orgs/{id}/ingest-financial-data` | yes | body = pre-parsed JSON financial data (same shape `fetch_990.py`/`bulk_ingest.py` produce) → stores a financial snapshot |
| GET | `/orgs/{id}/financial-snapshot` | yes | returns the latest ingested financial snapshot, or `{"snapshot": null}` if none exists yet |
| POST | `/orgs/{id}/dimensions` | yes | `{legal, governance, strategy, trackRecord, outcomes, leadership, reporting}` (0-100 each) → sets the 7 non-financial dimension scores |
| GET | `/orgs/{id}/score` | yes | computes and returns the full 8-dimension readiness score |
| POST | `/orgs/{id}/reports` | yes | `{updateText, overallBefore?, overallAfter?, dimensions?}` → logs an outcome update |
| GET | `/orgs/{id}/reports` | yes | list an org's outcome-report history |
| POST | `/funders` | yes | `{name, focus?, grantRange?, approach?, weights}` — `weights` keyed by dimension name, e.g. `"Financial Health": 30` |
| GET | `/funders` | no | list all funders |
| GET | `/funders/{id}/rank` | yes | ranks all of your orgs by that funder's weighted rubric |

## Bulk-loading nonprofit data for free (no Candid license needed)

`bulk_ingest.py` loads financial data for a list of organizations from
ProPublica's free, no-key-required Nonprofit Explorer API — a free
alternative to a paid Candid data license for the core financial numbers
(revenue, expenses, assets, contributions). It reuses `fetch_990.py`'s
ProPublica mapping so there's one source of truth for that transformation.

```bash
python3 bulk_ingest.py --token <your-auth-token> --input sample_eins.csv
```

Give it a CSV with an `ein` column (see `sample_eins.csv`); it creates each
org via the backend's own API if it doesn't exist yet, fetches its latest
filing from ProPublica, and posts the result to
`/orgs/{id}/ingest-financial-data`.

**Tested:** the CSV parsing, org create/lookup, the new
`/ingest-financial-data` endpoint, and the full script's control flow were
run end-to-end against a live local server (with the ProPublica network
call mocked using `sample_propublica_response.json`, a fixture matching
ProPublica's real documented response shape) — confirmed it correctly loads
an org with data, and correctly creates-but-skips an org with no filings on
ProPublica. **Not tested:** the actual live call to ProPublica's servers,
since this sandbox has no outbound network access. Run it against 2-3 real
EINs first once you have connectivity to confirm the numbers look right
before pointing it at a full list.

This gets you real financial data pre-loaded into your own database for
free. It won't get you Candid's added curation (mission summaries, logos,
demographics, keyword search) — that specifically requires a Candid API
account and is a separate integration if you decide you need it.

## Exporting to Excel

`export_to_excel.py` is the reverse direction: pulls every organization's
latest financial snapshot and readiness score out of a running backend and
writes them into an Excel workbook — the same Portfolio Scorecard layout
(and the same formulas) as the standalone template, via a shared module
(`portfolio_sheet.py`) so the two can't drift apart.

```bash
python3 export_to_excel.py --token <your-auth-token> --output portfolio.xlsx
```

`build_template.py` generates the blank/example version (what you'd hand
someone before any real data exists) using the same shared sheet builder:

```bash
python3 build_template.py my-template.xlsx
```

**Tested end-to-end**, including a real bug caught along the way: initially,
an org with no ingested financial data got a *misleadingly computed*
Financial Health score (60) from zeroed-out inputs, instead of matching the
backend's own honest "no data, neutral default" score (50). Fixed by adding
a guard to the Financial Health formula in `portfolio_sheet.py` so it
matches `scoring.py` exactly in that case. Verified afterward: an org with
real financial data and manual scores exported to a workbook whose
recalculated formulas produced 85.8/"Ready" — identical, to one decimal
place, to what `GET /orgs/{id}/score` returned directly from the API. An org
with no financial data correctly produced Financial Health 50 and overall
52.5/"Not Ready" in both the API and the exported spreadsheet.

**One infrastructure note that cost real debugging time:** repeatedly
overwriting the same `.xlsx` filename in place (as opposed to writing once
to a fresh path) corrupted the file in a way that made LibreOffice hang
indefinitely on recalculation, rather than erroring cleanly. Both scripts
here write to a scratch temp file first and only touch the final output
path once, at the end. If you build your own tooling on top of this, keep
that pattern — don't `wb.save()` over the same path in a loop.

## What's real vs. what's stubbed

**Real and tested:** auth (PBKDF2 password hashing, HMAC-signed tokens,
rejects bad/missing/expired tokens), SQLite persistence, the 990 XML parser
(against `sample_990.xml`, a realistic fixture), deterministic Financial
Health scoring from real ingested numbers (reserve-months, revenue
concentration, surplus/deficit — see `scoring.py`), and the funder-weighted
ranking math.

**Stubbed, with a clear seam to make it real:**
- **Live 990 fetching.** `fetch_990.py` calls ProPublica's public Nonprofit
  Explorer API (`https://projects.propublica.org/nonprofits/api/v2/organizations/{ein}.json`,
  free, no key needed) and maps its response into the same shape
  `/ingest-990` expects. It's written against ProPublica's real, documented
  API — but it has **not been run** in this environment because there's no
  network access here. Verify the exact JSON key names once you run it
  somewhere with connectivity; the IRS also publishes raw 990 XML in a public
  AWS Open Data bucket if you want the full filing rather than ProPublica's
  summary fields.
- **The 7 non-financial dimensions** (legal, governance, strategy, track
  record, outcomes, leadership, reporting) currently need `POST
  /orgs/{id}/dimensions` to be called manually. In the browser demo, these
  came from an LLM reading a free-text org description. This backend has no
  LLM API key wired in, so it doesn't call one — wire your own
  Anthropic/OpenAI key into a new `ai_scoring.py` module and call it from
  `_set_dimensions` (or a new endpoint) to automate this the way the demo
  does.
- **Auth is real but minimal.** Bearer tokens, password hashing, and
  rejection of bad credentials all work and are tested below — there's no
  password reset, email verification, or rate limiting yet.

## What was actually tested (this exact run)

```
register -> 201, token issued
create org "Bright Path Youth Alliance" -> id 1
ingest sample_990.xml -> parsed: revenue $2,415,000, expenses $2,260,000,
  net assets $1,120,000, contributions $1,680,000, program revenue $410,000
set manual dimensions (legal 90, governance 85, ...) -> saved
GET score -> Financial Health: 86/100, note: "~5.9 months of operating
  reserves, 70% revenue concentration in top source, surplus of $155,000"
  -> overall 85.8, status "Ready"
GET score again -> still 85.8 (manual dims correctly persisted, not
  shadowed by the score-history log - this was a real bug caught and fixed
  during testing, see manual_dimensions table in db.py)
create org #2 "Riverside Community Kitchen", no 990 ingested -> Financial
  Health defaults to neutral 50, overall 50.0, status "Not Ready"
create funder "North Star Family Foundation" (weights favor Financial
  Health at 30%)
GET /funders/{id}/rank -> Bright Path 85.7, Riverside 48.8 (correctly
  ordered and differentiated)
POST + GET /orgs/{id}/reports -> logged and retrieved correctly
no token -> 401 | garbage token -> 401 | wrong password -> 401 |
  duplicate email registration -> 409
```

## Deploying this somewhere real

This can't be deployed live from the environment it was built in (no
outbound network access there at all). A `Dockerfile` and `render.yaml` are
included so deployment is close to one step once you have a host connected:

- **Render:** the included `render.yaml` blueprint deploys this as a Docker
  web service with a persistent disk for the SQLite file (Render's
  filesystem is otherwise wiped on redeploy). `GRANTPASS_SECRET` is
  auto-generated by the blueprint.
- **Railway:** auto-detects the `Dockerfile`, no extra config needed — just
  set `GRANTPASS_SECRET` as an environment variable after the first deploy.
- **Anything else that runs Docker** (Fly.io, a plain VPS, etc.): `docker
  build -t grantpass . && docker run -p 8420:8420 -e GRANTPASS_SECRET=<random> grantpass`.

Either way: set `GRANTPASS_SECRET` to a long random value, then point the
front-end demo artifact's calls at this server's URL instead of (or
alongside) `window.cowork.askClaude` — that's the wiring step that connects
the two pieces built in this conversation.

## Files

- `server.py` — HTTP server and routing
- `db.py` — SQLite schema and connection helper
- `auth.py` — password hashing + bearer token signing/verification
- `parsing.py` — IRS 990 XML parser
- `scoring.py` — the 8-dimension rubric + deterministic financial scoring
- `fetch_990.py` — ProPublica API client + response-to-snapshot mapping (mapping logic tested against a fixture; the live network call is not)
- `bulk_ingest.py` — loads a CSV of EINs into the backend for free via ProPublica (control flow tested end-to-end with a mocked network call)
- `portfolio_sheet.py` — shared Excel sheet builder used by both `build_template.py` and `export_to_excel.py`
- `build_template.py` — generates the blank/example Portfolio Scorecard workbook
- `export_to_excel.py` — exports live backend data into the same workbook layout (tested end-to-end against a running server)
- `sample_990.xml` — 990 XML fixture used in the run log above
- `sample_propublica_response.json` — ProPublica response fixture used to test `bulk_ingest.py`
- `sample_eins.csv` — template input for `bulk_ingest.py`
