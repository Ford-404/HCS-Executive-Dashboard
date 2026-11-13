"""Usage:
  python -m report                      # pull from Procore, build PDF, email it
  python -m report --no-email           # build PDF + email preview only
  python -m report --fixture tests/fixtures --no-email   # no credentials needed
  python -m report --inspect            # dump one raw project + prime contract to check field mapping

Exit code 0 = report built (and sent if enabled); 1 = failed (a failure notice is emailed if email is enabled).
"""

from __future__ import annotations

import argparse
import html as htmllib
import json
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

try:  # corporate HTTPS inspection: verify against the Windows certificate store
    import truststore
    truststore.inject_into_ssl()
except ImportError:  # pragma: no cover
    pass

from . import mailer
from .build import build_report, totals
from .procore import FixtureClient, ProcoreAdapter
from .render import all_rows, diff, load_previous, render_email, render_pdf, snapshot

log = logging.getLogger("report")


def load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def make_client(args, config):
    if args.fixture:
        return FixtureClient(args.fixture)
    pc = config.get("procore", {})
    return ProcoreAdapter(env_file=args.env, prime_contract_path=pc.get("prime_contract_path"),
                          company_id=pc.get("company_id"))


def setup_logging(verbose: bool, log_dir: Path | None) -> None:
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / f"report_{datetime.now():%Y-%m-%d_%H%M%S}.log", encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(message)s", force=True)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def run(args, config) -> int:
    client = make_client(args, config)

    if args.inspect:
        p = client.list_projects(config.get("filters", {}).get("status", "Active"))[0]
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
        raise RuntimeError("No projects matched the filters; not sending an empty report.")
    grand = totals(all_rows(groups))
    log.info("%d projects, current contract total $%s", grand["count"], f"{grand['current']:,.2f}")

    stamp = now.date().isoformat()
    pdf = render_pdf(groups, config, out / f"{config['report'].get('filename', 'National_Active_Project_Summary')}_{stamp}.pdf", now)

    # Only real sends write the week-over-week history, so "what changed" always compares against the
    # last report execs received. Fixture and --no-email runs read it but keep their own copy in out/.
    history = Path(config.get("snapshot_dir", out / "snapshots"))
    snap_dir = out / "snapshots" if (args.fixture or args.no_email) else history
    if args.no_email and not args.fixture and history.exists():
        snap_dir.mkdir(parents=True, exist_ok=True)
        for f in history.glob("snapshot-*.json"):
            (snap_dir / f.name).write_bytes(f.read_bytes())
    snap_dir.mkdir(parents=True, exist_ok=True)
    deltas, changes = diff(load_previous(snap_dir, now.date()), groups)
    (snap_dir / f"snapshot-{stamp}.json").write_text(json.dumps(snapshot(groups), indent=1), encoding="utf-8")

    html = render_email(groups, config, now, deltas, changes)
    (out / "email_preview.html").write_text(html, encoding="utf-8")
    log.info("Wrote %s and %s", pdf, out / "email_preview.html")

    email = dict(config["email"])
    if args.no_email:
        email["enabled"] = False
    subject = email["subject"].format(date=f"{now.month}/{now.day}/{now.year}")
    log.info("Email: %s", mailer.send(email, subject, html, pdf, out / stamp))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="report")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--env", default=".env", help="file with PROCORE_* credentials (default .env)")
    ap.add_argument("--out", default="out")
    ap.add_argument("--fixture", help="read Procore data from saved JSON instead of the API")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    config = load_config(args.config)
    setup_logging(args.verbose, None if args.inspect else Path(config.get("log_dir", "logs")))
    try:
        return run(args, config)
    except Exception as exc:  # noqa: BLE001
        log.exception("Report run failed")
        email = config.get("email", {})
        if email.get("enabled", True) and not (args.no_email or args.inspect or args.fixture):
            try:
                body = (f"<p>The {htmllib.escape(config['report']['title'])} run failed:</p>"
                        f"<pre>{htmllib.escape(str(exc))}</pre>"
                        f"<pre style='color:#666'>{htmllib.escape(traceback.format_exc()[-3000:])}</pre>"
                        f"<p>Logs are in {htmllib.escape(str(Path(config.get('log_dir', 'logs')).resolve()))} on the report PC.</p>")
                failure_to = email.get("failure_to") or email.get("to")
                mailer.send({**email, "to": failure_to, "cc": []},
                            f"FAILED: {config['report']['title']} {datetime.now():%m/%d/%Y}",
                            body, None, Path(args.out) / "failed")
            except Exception:  # noqa: BLE001
                log.exception("Could not send the failure notice")
        return 1


if __name__ == "__main__":
    sys.exit(main())
