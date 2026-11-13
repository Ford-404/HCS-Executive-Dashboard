# Handoff: National Active Project Summary (weekly exec report)

Context from the Claude Code session where this was built
(https://claude.ai/code/session_01GcuFLrpPbeopYcQCrZN4Ey). Read this before changing anything.

## Goal
Replace the manually exported Procore custom report *"National Active Project Summary"* with an
automated version. Pull the data from the Procore API, render a PDF, and email it to the executive team weekly.

## Status (updated Nov 12, 2026)
- Wired to the **HCS Safety Scorecard's Procore client and service account** (`report/procore_base.py`, vendored;
  `report/procore.py` → `ProcoreAdapter`). Auth, project list, project detail and prime contracts all work live.
- **Field mapping verified live**: region, sq ft and owner type come from the project detail endpoint
  (`fetch_project_detail: true`). Contract amounts and dates match the export to the cent on Marshall Trade Center.
  Siemens TI differs by $93,011 only because CO #002 went back to *draft* on Nov 11.
- **Procore permissions fixed Nov 12.** The service account (shown as "HCS Technology API") has Prime Contracts **Admin**
  in its project template, because the contracts are private and Read Only can't see them. All 39 now return a prime contract.
- **Live reconciliation Nov 12 vs the Nov 6 export:** Original matches to the cent on all 39. Sq ft, owner type, region and dates all match.
  Approved is +$94,269.27, pending −$3,055,891.13 and current −$2,961,621.86, on 11 projects that all had change order activity after Nov 6.
  Pending moves are not fully explained by CO packages (e.g. Project 10X +$5.74M pending), so confirm against a same-day Procore export.
- **Runs on the Safety report's Windows PC** (Task Scheduler, `scheduling/`), not GitHub Actions. Email goes through OneDrive and
  the existing Power Automate flow (`email.method: onedrive`). PDF is rendered by Chrome/Edge on Windows (WeasyPrint needs GTK).
  The GitHub workflow is now tests only.
- `email.to` is just Ford for now. Swap in the exec distribution after the first good live send.
- `pytest` passes 8 tests (the 6 Nov 6 reconciliation tests, plus partial-contract refusal and the pinned project list).

## Decisions made
| Topic | Decision |
|---|---|
| Columns | Original = prime contract `grand_total`; Approved = `approved_change_orders`; Pending All = `pending_change_orders`; Total PCCO = Approved + Pending; **Current = Original + Approved + Pending (includes pending)**. This matches the Procore report. |
| Project selection | `filters.include_names` pins the 39 projects from the Nov 6 export (Procore has 71 Active). New projects must be added there. |
| Multiple prime contracts | Amounts are summed per project. Start date is the earliest; completion dates are the latest. |
| Precision | Full precision is kept until display. Procore stores sub-cent values, so its printed subtotals can be one cent off from the sum of its printed rows. |
| Grouping/sort | Rows are grouped by region (`project_region`) and sorted by owner type (HIP → Properties → Third Party), then by square footage descending with blanks last. |
| Owner-type totals (requested) | **HIP** = Hillwood Investment Properties, **Properties** = Hillwood Properties - Alliance, **Third Party**. Configured in `config.yaml → owner_type_groups`. Appears on PDF page 1 (summary table + region × owner grid), as in-region subtotal rows (only in regions with more than one type), and in the email. Unmapped values get their own bucket. |
| Layout | Formatting changes were approved. Page 1 = KPIs + owner-type summary + region × owner grid. Pages 2+ = project detail. |
| Email | HTML summary in the body (KPIs with week-over-week deltas, owner-type table, region table, "what changed") plus the PDF attachment. Sent through the Safety report's Power Automate flow (`onedrive`); `outlook`, `graph` and `smtp` are also available. Failure notices go to `email.failure_to` (default: `email.to`). |
| Week-over-week | Each run writes a JSON snapshot to `data/snapshots`. The next run compares against the latest snapshot. Only real sends write there. Fixture and `--no-email` runs keep their snapshot in `out/snapshots`. Baseline: the live Nov 12 snapshot. |
| Schedule | Windows Task Scheduler on the Safety report PC, Fridays 7:00 AM local (`scheduling/install_task.ps1`). Moved off GitHub Actions on Nov 12 because email goes through OneDrive + Power Automate. |

## Expected numbers (Nov 6, 2026 export) for reconciling the live API
- 39 projects, 24,027,072 sq ft
- Original $1,774,432,693.62 · Approved $549,706,168.28 · Pending $4,533,764.55 · Total PCCO $554,239,932.83 · Current $2,328,672,626.44
- HIP 23 projects / $1,149,773,486.19 current · Properties 11 / $599,543,859.17 · Third Party 5 / $579,355,281.09
- Regions (current): CA $152,132,023.72 · Midsouth $342,659,728.79 · Northeast $323,015,373.20 · Southeast $154,966,218.82 · Texas $1,355,899,281.91

## Open questions
1. **Same-day reconciliation.** Export the Procore report and run `python -m report --no-email` on the same day, then compare to the cent,
   especially Pending All. Check this before switching `email.to` to the exec list.
2. **Project selection.** The 39 are pinned. Should new projects be added by hand, or should the rule be "every Active project
   with a prime contract"?
3. Whether execs want Current Contract to include pending change orders (it does today, matching Procore).
4. Blank vs $0: the API returns `0.0` where Procore's report printed blank for pending (display only, totals unaffected).
5. Data issues noticed in the export: Continental Tire, IL is under HCS California; Legacy Park 10 Earthwork has the same sq ft as Marshall
   Trade Center (1,149,120); Schluter and 2929 Carlisle are still active with past completion dates; ACN4 – Celestica TI has
   $263.9M approved PCCOs on a $43.6M original contract.

## Procore client
`report/procore_base.py` is a verbatim copy of the Safety Scorecard's `src/procore_client.py`, which handles OAuth, rate limiting,
retries and the Windows cert store. Keep fixes in sync. `ProcoreAdapter` in `report/procore.py` exposes the three methods the report
uses: `list_projects`, `get_project` and `list_prime_contracts`.

## Layout
```
report/procore.py      ProcoreAdapter + FixtureClient (offline)
report/procore_base.py Procore client vendored from HCS-Safety-Scorecard
report/build.py        rows, region groups, owner-type segments, sort, filters
report/render.py       PDF (WeasyPrint or Chrome/Edge) + email rendering, week-over-week diff
report/mailer.py       onedrive (Power Automate) / outlook / graph / smtp delivery
report/__main__.py     CLI: --fixture, --no-email, --inspect
report/templates/      report.html (PDF), email.html
config.yaml            filters, field map, owner-type groups, recipients
tests/                 fixtures from the Nov 6 PDF + tests
scheduling/            Windows setup, Task Scheduler install, run_weekly.bat
docs/                  power-automate-flow.md
```
