# Handoff: National Active Project Summary (weekly exec report)

Context from the Claude Code session where this was built
(https://claude.ai/code/session_01GcuFLrpPbeopYcQCrZN4Ey). Read this before changing anything.

## Goal
Replace the manually exported Procore custom report *"National Active Project Summary"* with an
automated version. Pull the data from the Procore API, render a PDF, and email it to the executive team weekly.

## Status
- Built and tested against **fixture data transcribed from the Nov 6, 2026 Procore PDF export**
  (`tests/fixtures/`). It has **not yet been run against the live Procore API**.
- The Procore API is in place on our side (an existing project already uses it). The next step is to wire this
  report to that existing client and credentials, then confirm the field mapping.
- `pytest` passes 6 tests. They check grand totals, region subtotals, row order, blank-vs-$0 handling and owner-type totals
  against the PDF.

## Decisions made
| Topic | Decision |
|---|---|
| Columns | Original = prime contract `grand_total`; Approved = `approved_change_orders`; Pending All = `pending_change_orders`; Total PCCO = Approved + Pending; **Current = Original + Approved + Pending (includes pending)**. This matches the Procore report. |
| Multiple prime contracts | Amounts are summed per project. Start date is the earliest; completion dates are the latest. |
| Precision | Full precision is kept until display. Procore stores sub-cent values, so its printed subtotals can be one cent off from the sum of its printed rows. |
| Grouping/sort | Rows are grouped by region (`project_region`) and sorted by owner type (HIP → Properties → Third Party), then by square footage descending with blanks last. |
| Owner-type totals (requested) | **HIP** = Hillwood Investment Properties, **Properties** = Hillwood Properties - Alliance, **Third Party**. Configured in `config.yaml → owner_type_groups`. Appears on PDF page 1 (summary table + region × owner grid), as in-region subtotal rows (only in regions with more than one type), and in the email. Unmapped values get their own bucket. |
| Layout | Formatting changes were approved. Page 1 = KPIs + owner-type summary + region × owner grid. Pages 2+ = project detail. |
| Email | HTML summary in the body (KPIs with week-over-week deltas, owner-type table, region table, "what changed") plus the PDF attachment. Backends: SMTP or Microsoft Graph (M365 usually blocks SMTP AUTH). |
| Week-over-week | Each run writes a JSON snapshot to `snapshot_dir`. The next run compares against the latest snapshot. |
| Schedule | GitHub Actions cron, Mondays 12:17 UTC (`.github/workflows/weekly-report.yml`), plus a manual-run button. A server cron line is in the README. |

## Expected numbers (Nov 6, 2026 export) for reconciling the live API
- 39 projects, 24,027,072 sq ft
- Original $1,774,432,693.62 · Approved $549,706,168.28 · Pending $4,533,764.55 · Total PCCO $554,239,932.83 · Current $2,328,672,626.44
- HIP 23 projects / $1,149,773,486.19 current · Properties 11 / $599,543,859.17 · Third Party 5 / $579,355,281.09
- Regions (current): CA $152,132,023.72 · Midsouth $342,659,728.79 · Northeast $323,015,373.20 · Southeast $154,966,218.82 · Texas $1,355,899,281.91

## Open questions / to confirm with live data
1. **Project selection.** The Procore export says "Filters: Project > Name", so it may be a hand-picked list. Today the tool takes all
   Active projects. If needed, set `filters.include_names`.
2. **Field locations.** Owner Type is the least certain (`project_owner_type.name` is assumed); Square Footage (`square_feet`) also needs checking.
   Run `python -m report --inspect` and adjust `field_map`.
3. **Prime contracts endpoint.** v1.0 `/rest/v1.0/prime_contract?project_id=` is assumed. The company may be on v2.0 prime contracts.
   `procore.prime_contract_path` is configurable.
4. Whether execs want Current Contract to include pending change orders (it does today, matching Procore).
5. Data issues noticed in the export: Continental Tire, IL is under HCS California; Legacy Park 10 Earthwork has the same sq ft as Marshall
   Trade Center (1,149,120); Schluter and 2929 Carlisle are still active with past completion dates; ACN4 – Celestica TI has
   $263.9M approved PCCOs on a $43.6M original contract.

## Integrating with the existing Procore project
`report/procore.py` contains a minimal client. The report only depends on three methods: `list_projects(status)`,
`get_project(id)` and `list_prime_contracts(project_id)`. The simplest integration is an adapter that implements those
three methods on top of the existing project's Procore client and auth, passed in where `make_client()` in
`report/__main__.py` builds the client. Everything downstream (build → render → email) stays unchanged.

## Layout
```
report/procore.py      API client + FixtureClient (offline)
report/build.py        rows, region groups, owner-type segments, sort, filters
report/render.py       PDF + email rendering, week-over-week diff
report/mailer.py       SMTP / Microsoft Graph delivery
report/__main__.py     CLI: --fixture, --no-email, --inspect
report/templates/      report.html (PDF), email.html
config.yaml            filters, field map, owner-type groups, recipients
tests/                 fixtures from the Nov 6 PDF + tests
```
