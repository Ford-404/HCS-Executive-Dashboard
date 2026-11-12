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
- Data source: the report depends only on `list_projects`, `get_project` and `list_prime_contracts`
  (see `report/procore.py`). To reuse another project's Procore client, write an adapter with those three methods.
- Never commit `.env` or credentials. Secrets come from environment variables / GitHub Actions secrets.
