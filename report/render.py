"""Render the PDF report and the HTML email body; compute week-over-week changes."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import sys
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .build import Group, Row, owner_segments, totals

TEMPLATES = Path(__file__).parent / "templates"
log = logging.getLogger(__name__)


def usd(v) -> str:
    if v is None:
        return ""
    v = Decimal(v)
    s = f"${abs(v):,.2f}"
    return f"({s})" if v < 0 else s


def short(v) -> str:
    """$2.33B / $554.2M / $812K: for executive-level summaries."""
    if v is None:
        return ""
    v = Decimal(v)
    a = abs(v)
    if a >= 1_000_000_000:
        s = f"${a / 1_000_000_000:,.2f}B"
    elif a >= 1_000_000:
        s = f"${a / 1_000_000:,.1f}M"
    elif a >= 1_000:
        s = f"${a / 1_000:,.0f}K"
    else:
        s = f"${a:,.0f}"
    return f"({s})" if v < 0 else s


def sqft(v) -> str:
    return f"{v:,}" if v else ""


def mdy(d) -> str:
    return f"{d.month}/{d.day}/{d.year}" if d else ""


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    env.filters.update(usd=usd, short=short, sqft=sqft, mdy=mdy)
    return env


def all_rows(groups: list[Group]) -> list[Row]:
    return [r for g in groups for r in g.rows]


def _named_segments(groups: list[Group], config: dict) -> list[dict]:
    names = {g["label"]: g.get("name", "") for g in config.get("owner_type_groups", [])}
    return [{**s, "name": names.get(s["label"], "")} for s in owner_segments(all_rows(groups), config)]


def _matrix(groups: list[Group], config: dict) -> dict:
    """{region: {owner label: totals}}"""
    return {g.region: {s["label"]: s["totals"] for s in g.segments(config)} for g in groups}


def stamp(dt: datetime, with_weekday: bool = True) -> str:
    """'Thursday, November 12, 2026 4:05 PM CST' without platform-specific strftime flags
    (%-d / %-I are glibc-only and fail on Windows)."""
    hour = dt.hour % 12 or 12
    head = f"{dt:%A}, {dt:%B} {dt.day}, {dt.year}" if with_weekday else f"{dt:%b} {dt.day}, {dt.year}"
    return f"{head} {hour}:{dt:%M} {'AM' if dt.hour < 12 else 'PM'} {dt.tzname() or ''}".strip()


def render_pdf(groups: list[Group], config: dict, out_path: Path, now: datetime) -> Path:
    rep = config["report"]
    html = _env().get_template("report.html").render(
        title=rep["title"],
        company_lines=rep.get("company_lines", []),
        footer_left=rep.get("footer", ""),
        groups=groups,
        grand=totals(all_rows(groups)),
        owner_segments=_named_segments(groups, config),
        matrix=_matrix(groups, config),
        config=config,
        generated_at=stamp(now),
    )
    write_pdf(html, out_path, rep.get("pdf_engine", "auto"))
    return out_path


# ---- PDF engines -------------------------------------------------------------
# WeasyPrint needs the Pango/GTK libraries, which are standard on Linux but not on
# Windows. Microsoft Edge (on every Windows PC) or Chrome renders the same HTML,
# including the @page footer and page numbers, so "auto" falls back to it.

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser", "msedge",
]
# Some managed Edge installs exit immediately in the new headless mode but still honour the old one.
HEADLESS_MODES = ["--headless=new", "--headless=old"]


def _browsers() -> list[str]:
    found = []
    for b in BROWSERS:
        exe = b if Path(b).is_file() else shutil.which(b)
        if exe and exe not in found:
            found.append(exe)
    return found


def _pdf_weasyprint(html: str, out_path: Path) -> None:
    from weasyprint import HTML  # imported lazily: heavy, and needs Pango
    HTML(string=html, base_url=str(TEMPLATES)).write_pdf(out_path)


def _wait_for_file(path: Path, timeout: float = 60) -> bool:
    """msedge.exe can hand off to a child process and exit before the PDF is written,
    so wait until the file exists and its size has stopped changing."""
    deadline, last = time.monotonic() + timeout, -1
    while time.monotonic() < deadline:
        size = path.stat().st_size if path.exists() else -1
        if size > 0 and size == last:
            return True
        last = size
        time.sleep(0.5)
    return False


def _pdf_browser(html: str, out_path: Path) -> str:
    browsers = _browsers()
    if not browsers:
        raise RuntimeError("No PDF engine: WeasyPrint's libraries are missing and Chrome/Edge was not found")
    out_path = out_path.resolve()
    tried = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:  # Edge can hold its profile briefly
        src = Path(tmp) / "report.html"
        src.write_text(html, encoding="utf-8")
        for exe in browsers:
            for mode in HEADLESS_MODES:
                out_path.unlink(missing_ok=True)
                cmd = [exe, mode, "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                       "--disable-extensions", f"--user-data-dir={Path(tmp) / 'profile'}",
                       "--no-pdf-header-footer", f"--print-to-pdf={out_path}", src.as_uri()]
                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                except subprocess.TimeoutExpired:
                    tried.append(f"{Path(exe).name} {mode}: timed out")
                    continue
                if _wait_for_file(out_path):
                    return f"{Path(exe).name} {mode}"
                tried.append(f"{Path(exe).name} {mode}: exit {proc.returncode} {proc.stderr.strip()[-200:]}")
    raise RuntimeError("No browser wrote the PDF: " + "; ".join(tried))


def write_pdf(html: str, out_path: Path, engine: str = "auto") -> str:
    if engine == "auto" and sys.platform == "win32":
        engine = "browser"  # WeasyPrint needs GTK on Windows; Chrome/Edge are already there
    if engine in ("weasyprint", "auto"):
        try:
            _pdf_weasyprint(html, out_path)
            return "weasyprint"
        except (ImportError, OSError) as exc:  # OSError = Pango/GTK libraries not installed
            if engine == "weasyprint":
                raise
            log.info("WeasyPrint unavailable (%s); rendering the PDF with Chrome/Edge", type(exc).__name__)
    if engine in ("browser", "edge", "chrome", "auto"):
        used = _pdf_browser(html, out_path)
        log.info("PDF rendered with %s", used)
        return used
    raise ValueError(f"Unknown report.pdf_engine: {engine}")


# ---- week-over-week -----------------------------------------------------------

def snapshot(groups: list[Group]) -> dict:
    return {"rows": [r.as_json() for r in all_rows(groups)]}


def load_previous(snapshot_dir: Path, today: date) -> dict | None:
    files = sorted(p for p in snapshot_dir.glob("snapshot-*.json") if p.stem < f"snapshot-{today.isoformat()}")
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def diff(prev: dict | None, groups: list[Group], max_items: int = 8) -> tuple[dict, list[str]]:
    """Returns (deltas for KPI cards, human-readable change bullets)."""
    if not prev:
        return {}, []
    old = {r["project_id"]: r for r in prev["rows"]}
    new = {r.project_id: r for r in all_rows(groups)}
    D = lambda x: Decimal(x) if x not in (None, "") else Decimal(0)

    deltas = {}
    for col in ("original", "approved", "pending", "current"):
        deltas[col] = sum((D(getattr(r, col)) for r in new.values()), Decimal(0)) - \
                      sum((D(r[col]) for r in old.values()), Decimal(0))

    changes = []
    for pid in new.keys() - old.keys():
        r = new[pid]
        changes.append(f"Added: {r.name} ({r.region}), {short(r.current)} current contract")
    for pid in old.keys() - new.keys():
        changes.append(f"No longer on report: {old[pid]['name']}")

    moves = []
    for pid in new.keys() & old.keys():
        r, o = new[pid], old[pid]
        d_appr = D(r.approved) - D(o["approved"])
        d_pend = D(r.pending) - D(o["pending"])
        if d_appr or d_pend:
            moves.append((abs(d_appr) + abs(d_pend), r.name, d_appr, d_pend))
        if o.get("substantial_completion") != (r.substantial_completion.isoformat() if r.substantial_completion else None) \
                and o.get("substantial_completion"):
            changes.append(f"{r.name}: substantial completion moved {mdy(date.fromisoformat(o['substantial_completion']))} → {mdy(r.substantial_completion)}")
    for _, name, d_appr, d_pend in sorted(moves, reverse=True)[:max_items]:
        parts = []
        if d_appr:
            parts.append(f"approved PCCOs {'+' if d_appr > 0 else '−'}{short(abs(d_appr))}")
        if d_pend:
            parts.append(f"pending PCCOs {'+' if d_pend > 0 else '−'}{short(abs(d_pend))}")
        changes.append(f"{name}: " + ", ".join(parts))
    return deltas, changes


def render_email(groups: list[Group], config: dict, now: datetime, deltas: dict, changes: list[str]) -> str:
    grand = totals(all_rows(groups))

    def fmt_delta(col):
        if col not in deltas or not deltas[col]:
            return "No change" if col in deltas else ""
        d = deltas[col]
        return f"{'+' if d > 0 else '−'}{short(abs(d))}"

    kpis = [
        ("Current contract", short(grand["current"]), fmt_delta("current")),
        ("Original contract", short(grand["original"]), fmt_delta("original")),
        ("Approved PCCOs", short(grand["approved"]), fmt_delta("approved")),
        ("Pending PCCOs", short(grand["pending"]), fmt_delta("pending")),
    ]
    return _env().get_template("email.html").render(
        title=config["report"]["title"],
        week_of=mdy(now.date()),
        groups=groups,
        grand=grand,
        kpis=kpis,
        owner_segments=_named_segments(groups, config),
        changes=changes,
        generated_at=stamp(now, with_weekday=False),
    )
