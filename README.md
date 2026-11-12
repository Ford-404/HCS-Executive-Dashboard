# HCS Executive Dashboard: National Active Project Summary

This tool pulls active projects and their prime contracts from the Procore API and rebuilds the
*National Active Project Summary* report. It renders the report as a PDF and emails it to the executive team every week. The email body gives
a short summary: headline numbers, a roll-up by region, and what changed since last week. The full
project-level report is attached as a PDF.

```
Procore API ──► build rows / region subtotals ──► PDF (WeasyPrint) ──► email (SMTP or Microsoft 365)
                                     └──► weekly snapshot ──► "what changed since last week"
```

## 1. Procore credentials (one-time)

1. In the [Procore Developer Portal](https://developers.procore.com), create an app and add a
   **Developer Managed Service Account** (DMSA).
2. A Procore company admin installs the app in **Company Admin → App Management** and gives the
   service account read access to **Projects**, **Directory** and **Prime Contracts** on every project.
   The report can only include projects the service account can see.
3. Copy the client ID and secret. Your company ID is in any Procore URL (`/companies/<id>/…`).

## 2. Try it locally

```bash
pip install -r requirements.txt
cp .env.example .env    # fill in values
set -a; . ./.env; set +a
```

Preview the layout without any credentials. This uses the data from the Nov 6, 2026 export:

```bash
python -m report --fixture tests/fixtures --no-email
```

Check that the field mapping matches your Procore setup. This dumps one project and its prime contract as raw JSON:

```bash
python -m report --inspect
```

Find Square Footage, Owner Type and Region in that output. If they live under different
keys, for example a company custom field, edit `field_map` in `config.yaml`. Then build the real report without sending it:

```bash
python -m report --no-email
```

Open `out/*.pdf` and `out/email_preview.html` and compare them against the PDF exported from Procore.

## 3. Schedule it

**GitHub Actions** (recommended): push this folder to a private repo and add the values from
`.env.example` as repository secrets (Settings → Secrets and variables → Actions). The workflow
`.github/workflows/weekly-report.yml` runs every Monday morning. You can also run it by hand from
the Actions tab, where unchecking "send email" builds the PDF without sending it. Every week's PDF is kept as a
build artifact for 90 days.

**Any server with cron**, as an alternative (example entry: Mondays 7:00 AM):

```
0 7 * * 1  cd /opt/procore-exec-report && set -a && . ./.env && python -m report >> report.log 2>&1
```

## 4. Email

Set `email.to`, `email.cc` and `email.from` in `config.yaml`.

- `backend: smtp` works with SendGrid, Mailgun, Google Workspace, or Microsoft 365 when SMTP AUTH is
  enabled on the sending mailbox.
- `backend: graph` is for Microsoft 365 tenants that block SMTP AUTH, which Microsoft does by default. It needs an Entra ID
  app registration with the **Mail.Send** application permission and admin consent. Use an
  [application access policy](https://learn.microsoft.com/graph/auth-limit-mailbox-access) to limit that app to the reports mailbox.

## How the columns are calculated

| Column | Source |
|---|---|
| Original Contract Amount | prime contract `grand_total` |
| Approved Amount | prime contract `approved_change_orders` |
| Pending All Amount | prime contract `pending_change_orders` |
| Total PCCO Amount | Approved + Pending |
| Current Contract Amount | Original + Approved + Pending. **This includes pending change orders**, matching the Procore report. |
| Start / Est. / Substantial Completion | prime contract date fields |

If a project has more than one prime contract, the amounts are added together. Rows are grouped by region and sorted by owner type (HIP, Properties, Third Party), then by
square footage (largest first). This matches the order in the Procore export.

`tests/test_report.py` checks these calculations against the totals printed on the Nov 6, 2026 Procore export.

## Owner-type totals

The first page of the PDF summarizes the work by owner type: **HIP** (Hillwood Investment Properties), **Properties**
(Hillwood Properties - Alliance) and **Third Party**. It shows full totals for each type and a region × owner-type grid.
In the project detail, a region with more than one owner type also gets a subtotal row for each type. The email includes the same
breakdown. The mapping lives in `owner_type_groups` in `config.yaml`. If Procore adds a new Owner Type value, add it to a
group's `match` list. Until then it appears as its own bucket, so it is never silently dropped.
