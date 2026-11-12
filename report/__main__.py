"""Usage:
  python -m report                      # pull from Procore, build PDF, email it
  python -m report --no-email           # build PDF + email preview only
  python -m report --fixture tests/fixtures --no-email   # no credentials needed
  python -m report --inspect            # dump one raw project + prime contract to check field mapping
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import mailer
from .build import build_report, totals
from .procore import FixtureClient, ProcoreClient
from .render import all_rows, diff, load_previous, render_email, render_pdf, snapshot

log = logging.getLogger("report")


def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text())


def make_client(args, config):
    if args.fixture:
        return FixtureClient(args.fixture)
    pc = config.get("procore", {})
    return ProcoreClient(
        client_id=os.environ["PROCORE_CLIENT_ID"],
        client_secret=os.environ["PROCORE_CLIENT_SECRET"],
        company_id=os.environ.get("PROCORE_COMPANY_ID") or pc["company_id"],
        environment=os.environ.get("PROCORE_ENV", pc.get("environment", "production")),
        prime_contract_path=pc.get("prime_contract_path"),
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="report")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--out", default="out")
    ap.add_argument("--fixture", help="read Procore data from saved JSON instead of the API")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    config = load_config(args.config)
    client = make_client(args, config)

    if args.inspect:
        p = client.list_projects()[0]
        detail = client.get_project(p["id"])
        print(json.dumps({"project_list_item": p, "project_detail": detail,
                          "prime_contracts": client.list_prime_contracts(p["id"])}, indent=2, default=str))
        return 0

    tz = ZoneInfo(config["report"].get("timezone", "America/Chicago"))
    now = datetime.now(tz)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    groups = build_report(client, config)
    if not groups:
        log.error("No projects matched the filters; not sending an empty report.")
        return 1
    grand = totals(all_rows(groups))
    log.info("%d projects, current contract total $%s", grand["count"], f"{grand['current']:,.2f}")

    stamp = now.date().isoformat()
    pdf = render_pdf(groups, config, out / f"{config['report'].get('filename', 'National_Active_Project_Summary')}_{stamp}.pdf", now)

    snap_dir = Path(config.get("snapshot_dir", out / "snapshots"))
    snap_dir.mkdir(parents=True, exist_ok=True)
    deltas, changes = diff(load_previous(snap_dir, now.date()), groups)
    (snap_dir / f"snapshot-{stamp}.json").write_text(json.dumps(snapshot(groups), indent=1))

    html = render_email(groups, config, now, deltas, changes)
    (out / "email_preview.html").write_text(html)
    log.info("Wrote %s and %s", pdf, out / "email_preview.html")

    if args.no_email:
        return 0
    subject = config["email"]["subject"].format(date=f"{now.month}/{now.day}/{now.year}")
    mailer.send(config["email"], subject, html, pdf)
    log.info("Emailed %s", ", ".join(config["email"]["to"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
