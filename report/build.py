"""Turn raw Procore records into report rows, grouped by region with subtotals.

Column definitions (reverse-engineered from the Procore custom report PDF and
checked against its totals):
  Original Contract Amount = prime contract grand total (original SOV)
  Approved Amount          = approved prime contract change orders
  Pending All Amount       = all pending prime contract change orders
  Total PCCO Amount        = Approved + Pending
  Current Contract Amount  = Original + Total PCCO   (note: includes pending)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import date
from decimal import Decimal

log = logging.getLogger(__name__)

MONEY_COLS = ["original", "approved", "pending", "total_pcco", "current"]


def get_path(obj, path: str):
    """Resolve 'a.b.c' through nested dicts. Supports 'custom_fields.<key>' where
    custom_fields is either a dict or a list of {label/key, value}."""
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            cur = next((x.get("value") for x in cur
                        if str(x.get("key")) == part or str(x.get("label")) == part
                        or str(x.get("id")) == part), None)
        else:
            return None
    if isinstance(cur, dict) and "value" in cur:  # custom field shape {"value": ...}
        cur = cur["value"]
    if isinstance(cur, dict) and "name" in cur:   # e.g. project_region {"id","name"}
        cur = cur["name"]
    return cur


def first(obj, paths: list[str]):
    for p in paths:
        v = get_path(obj, p)
        if v not in (None, ""):
            return v
    return None


def money(v) -> Decimal | None:
    if v in (None, ""):
        return None
    # Keep full precision: Procore stores sub-cent amounts and rounds only for
    # display, so rounding here would make subtotals drift by a cent.
    return Decimal(str(v))


def parse_date(v) -> date | None:
    if not v:
        return None
    return date.fromisoformat(str(v)[:10])


@dataclass
class Row:
    project_id: int
    name: str
    region: str
    square_feet: int | None
    owner_type: str | None
    original: Decimal | None
    approved: Decimal | None
    pending: Decimal | None
    total_pcco: Decimal | None
    current: Decimal | None
    start_date: date | None
    est_completion: date | None
    substantial_completion: date | None

    def as_json(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = str(v)
            elif isinstance(v, date):
                d[k] = v.isoformat()
        return d


@dataclass
class Group:
    region: str
    rows: list[Row] = field(default_factory=list)

    @property
    def totals(self) -> dict:
        return totals(self.rows)

    def segments(self, config: dict) -> list[dict]:
        """Owner-type subtotals within this region, in the configured order."""
        return owner_segments(self.rows, config)


def totals(rows: list[Row]) -> dict:
    t = {c: sum((getattr(r, c) or Decimal(0) for r in rows), Decimal(0)) for c in MONEY_COLS}
    t["square_feet"] = sum(r.square_feet or 0 for r in rows)
    t["count"] = len(rows)
    return t


def owner_label(owner_type: str | None, config: dict) -> str:
    for g in config.get("owner_type_groups", []):
        if owner_type in g["match"]:
            return g["label"]
    return owner_type or "Unassigned"


def owner_segments(rows: list[Row], config: dict) -> list[dict]:
    """Group rows into HIP / Properties / Third Party (per config), keeping the
    configured order and appending anything unmapped at the end."""
    order = [g["label"] for g in config.get("owner_type_groups", [])]
    buckets: dict[str, list[Row]] = {}
    for r in rows:
        buckets.setdefault(owner_label(r.owner_type, config), []).append(r)
    labels = [l for l in order if l in buckets] + sorted(l for l in buckets if l not in order)
    return [{"label": l, "rows": buckets[l], "totals": totals(buckets[l])} for l in labels]


def _sum(values):
    vals = [v for v in values if v is not None]
    return sum(vals, Decimal(0)) if vals else None


def build_row(project: dict, contracts: list[dict], fm: dict) -> Row:
    contracts = [c for c in contracts if not c.get("deleted_at")]
    original = _sum(money(first(c, fm["original"])) for c in contracts)
    approved = _sum(money(first(c, fm["approved"])) for c in contracts)
    pending = _sum(money(first(c, fm["pending"])) for c in contracts)

    total_pcco = None if approved is None and pending is None else (approved or 0) + (pending or 0)
    current = None if original is None and total_pcco is None else (original or 0) + (total_pcco or 0)

    def dates(paths, pick):
        ds = [d for d in (parse_date(first(c, paths)) for c in contracts) if d]
        return pick(ds) if ds else None

    sqft = first(project, fm["square_feet"])
    try:
        sqft = int(float(str(sqft).replace(",", ""))) if sqft not in (None, "") else None
    except ValueError:
        sqft = None

    if not contracts:
        log.warning("Project %s (%s) has no prime contract", project.get("name"), project.get("id"))

    return Row(
        project_id=project["id"],
        name=project.get("name", ""),
        region=first(project, fm["region"]) or "Unassigned",
        square_feet=sqft,
        owner_type=first(project, fm["owner_type"]),
        original=original,
        approved=approved,
        pending=pending,
        total_pcco=total_pcco,
        current=current,
        start_date=dates(fm["start_date"], min),
        est_completion=dates(fm["est_completion"], max),
        substantial_completion=dates(fm["substantial_completion"], max),
    )


def include_project(project: dict, filters: dict, fm: dict) -> bool:
    name = project.get("name", "")
    region = first(project, fm["region"]) or ""
    if filters.get("include_names") and name not in filters["include_names"]:
        return False
    if name in (filters.get("exclude_names") or []):
        return False
    if filters.get("include_regions") and region not in filters["include_regions"]:
        return False
    if region in (filters.get("exclude_regions") or []):
        return False
    stages = filters.get("include_stages")
    if stages and first(project, ["project_stage.name", "project_stage"]) not in stages:
        return False
    return True


def sort_key(config: dict):
    # Matches the Procore report: owner type (in configured order), then largest
    # square footage first, blanks last.
    order = [g["label"] for g in config.get("owner_type_groups", [])]

    def key(r: Row):
        lbl = owner_label(r.owner_type, config)
        rank = order.index(lbl) if lbl in order else len(order)
        return (rank, lbl, r.square_feet is None, -(r.square_feet or 0), r.name)
    return key


def build_report(client, config: dict) -> list[Group]:
    fm = config["field_map"]
    filters = config.get("filters", {})
    projects = client.list_projects(filters.get("status", "Active"))
    log.info("Fetched %d projects", len(projects))

    rows = []
    with_contracts = 0
    for p in projects:
        if filters.get("include_names") and p.get("name") not in filters["include_names"]:
            continue  # skip the detail call for projects that can't be on the report
        if config.get("fetch_project_detail"):
            p = {**p, **client.get_project(p["id"])}
        if not include_project(p, filters, fm):
            continue
        contracts = client.list_prime_contracts(p["id"])
        with_contracts += bool(contracts)
        rows.append(build_row(p, contracts, fm))

    missing = set(filters.get("include_names") or []) - {p.get("name") for p in projects}
    for name in sorted(missing):
        log.warning("Listed in filters.include_names but not an %s project in Procore: %s",
                    filters.get("status", "Active"), name)
    need = float(config.get("min_contract_coverage", 0.9))
    if rows and with_contracts < need * len(rows):
        raise RuntimeError(
            f"Only {with_contracts} of {len(rows)} projects returned a prime contract (need {need:.0%}, "
            "min_contract_coverage in config.yaml). The Procore service account most likely lacks Prime "
            "Contracts access on the other projects. Not sending a report with missing contract amounts.")
    log.info("%d projects on the report, %d with prime contracts", len(rows), with_contracts)

    groups: dict[str, Group] = {}
    for r in rows:
        groups.setdefault(r.region, Group(r.region)).rows.append(r)
    for g in groups.values():
        g.rows.sort(key=sort_key(config))
    return [groups[k] for k in sorted(groups)]
