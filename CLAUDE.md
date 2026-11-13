# HCS Executive Dashboard

Weekly "National Active Project Summary" report: Procore API → PDF → email to the executive team.

**Read `HANDOFF.md` first.** It records the decisions made so far (column definitions, HIP / Properties /
Third Party grouping, layout), the Nov 6, 2026 totals to reconcile against, and open questions.
`README.md` covers setup, scheduling and email.

## Working here
- Run tests: `pytest -q`. They compare against totals from the Nov 6, 2026 Procore export. Keep them passing.
- Preview without credentials: `python -m report --fixture tests/fixtures --no-email`. Output goes to `out/`.
- Check the API field mapping: `python -m report --inspect`.
- Money stays `Decimal` at full precision until display. Do not round when reading from Procore.
- Data source: `ProcoreAdapter` (`report/procore.py`) wraps `report/procore_base.py`, a verbatim copy of the
  HCS-Safety-Scorecard client. The report only uses `list_projects`, `get_project` and `list_prime_contracts`.
- Production runs on the Safety report's Windows PC (Task Scheduler). Email goes through OneDrive and that repo's Power Automate flow.
  Use Windows-safe code: `encoding="utf-8"` on every file read/write, and no `%-d`-style strftime flags.
- Never commit `.env` or credentials. Secrets live in `.env` on the PC (same service account as the Safety report).
- Don't run without `--no-email` unless you mean to send. `email.method: onedrive` writes into the real OneDrive Outbox.
