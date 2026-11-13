# HCS Executive Dashboard: National Active Project Summary

This tool rebuilds the Procore custom report *National Active Project Summary* from the Procore API, renders it as a PDF and
emails it to the executive team every Friday morning. The email body gives the headline numbers, owner-type and region
roll-ups, and what changed since last week. The full project-level report is attached as a PDF.

```
Procore API ──► rows / region + owner-type subtotals ──► PDF (Chrome/Edge on Windows) ──► OneDrive Outbox ──► Power Automate ──► email
                                      └──► data/snapshots ──► "what changed since last week"
```

It runs on the same always-on Windows PC as the **HCS Safety Health Report**
([Ford-Tough/HCS-Safety-Scorecard](https://github.com/Ford-Tough/HCS-Safety-Scorecard)). It uses the same Procore
service account and client (`report/procore_base.py`), the same Power Automate email flow, and the same Task Scheduler setup.

## 1. Procore access

The report uses the Safety Scorecard's service account, which appears in Procore as **HCS Technology API**. Prime contracts here are
*private*, and private contracts are only visible to Prime Contracts **Admin** users or to users added to each contract. The app's project
permission template is therefore Read Only everywhere except **Prime Contracts = Admin** (set Nov 12, 2026). A project only shows up if it
uses that template. Check this when adding new projects (Company Admin → Directory → HCS Technology API → Change Template).

The report refuses to send unless at least 90% of its projects return a prime contract (`min_contract_coverage`). Otherwise it emails
a failure notice, so execs never get a total with most contracts missing.

## 2. Set up the PC (one-time)

```powershell
git clone https://github.com/Ford-Tough/HCS-Executive-Dashboard.git
cd HCS-Executive-Dashboard
powershell -ExecutionPolicy Bypass -File scheduling\setup_windows.ps1
```

This creates `.venv` and installs requirements. If `..\hcs-safety-report\.env` exists, it copies the Procore credentials
from there. Otherwise, fill in `.env` from `.env.example`.

Preview without credentials (data from the Nov 6, 2026 export):

```powershell
.\.venv\Scripts\python.exe -m report --fixture tests/fixtures --no-email
```

Build the live report without sending it, and compare `out\*.pdf` against the Procore export:

```powershell
.\.venv\Scripts\python.exe -m report --no-email
```

`python -m report --inspect` dumps one raw project and its prime contract, which helps if Procore's fields change.

## 3. Email

Email goes through OneDrive and the Safety Health Report's Power Automate flow. You don't need a new flow. See
[docs/power-automate-flow.md](docs/power-automate-flow.md). Set recipients in `config.yaml`:

```yaml
email:
  to: [...]          # starts as just you; replace with the executive distribution once approved
  cc: []
  failure_to: []     # who gets "FAILED: ..." notices (default: email.to)
```

Other methods (`outlook`, `graph`, `smtp`) are available via `email.method`. Every run saves the exact email to
`out\<date>\email.html` / `.eml`.

## 4. Schedule it

```powershell
powershell -ExecutionPolicy Bypass -File scheduling\install_task.ps1     # Fridays 7:00 AM (PC local time)
Start-ScheduledTask -TaskName "HCS National Active Project Summary"     # run it now
```

The task runs as the signed-in user, because OneDrive sync needs the user session. Lock the PC rather than signing out. Logs are in
`logs\`. Last week's numbers are kept in `data\snapshots\` for the "what changed" section.

GitHub Actions (`.github/workflows/tests.yml`) only runs the tests and renders the fixture report on each push.

## Project selection

The Procore report is filtered by *Project > Name*. Procore has 71 Active projects, and the report has a hand-picked 39
(the excluded ones include overhead and fee projects). Those 39 names are in `filters.include_names` in `config.yaml`. **Add new
projects there.** A listed name that is no longer Active is logged as a warning. Empty the list to include every Active project.

## How the columns are calculated

| Column | Source |
|---|---|
| Original Contract Amount | prime contract `grand_total` |
| Approved Amount | prime contract `approved_change_orders` |
| Pending All Amount | prime contract `pending_change_orders_amount` |
| Total PCCO Amount | Approved + Pending |
| Current Contract Amount | Original + Approved + Pending. **This includes pending change orders**, matching the Procore report. |
| Start / Est. / Substantial Completion | prime contract `contract_start_date`, `contract_estimated_completion_date`, `substantial_completion_date` |
| Region / Square Footage / Owner Type | project `project_region`, `square_feet`, `project_owner_type` (single-project endpoint only) |

All of these were checked against live Procore on Nov 12, 2026. Draft change orders are not counted, which matches Procore's report.
If a project has more than one prime contract, the amounts are added together. Rows are grouped by region and sorted by owner
type (HIP, Properties, Third Party), then by square footage (largest first).

`tests/test_report.py` checks these calculations against the totals printed on the Nov 6, 2026 Procore export.

## Owner-type totals

The first page of the PDF summarizes the work by owner type: **HIP** (Hillwood Investment Properties), **Properties**
(Hillwood Properties - Alliance) and **Third Party**. It shows full totals for each type and a region × owner-type grid. In the project
detail, a region with more than one owner type also gets a subtotal row for each type. The mapping lives in `owner_type_groups` in
`config.yaml`. An unmapped Owner Type gets its own bucket, so it is never silently dropped.
