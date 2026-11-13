"""The fixtures reproduce the Procore export dated Nov 6, 2026. These tests check
that our calculations match Procore's printed totals to the cent."""

from decimal import Decimal as D
from pathlib import Path

import yaml

from report.build import build_report, owner_segments, totals
from report.procore import FixtureClient
from report.render import all_rows, usd

ROOT = Path(__file__).parent.parent
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def close(a, b):
    # Fixtures were transcribed from the PDF, i.e. already rounded to cents, while
    # Procore totals its unrounded values. Allow the resulting 1-cent drift.
    return abs(a - D(b)) <= D("0.01")


def groups():
    return build_report(FixtureClient(ROOT / "tests/fixtures"), CONFIG)


def test_grand_totals_match_procore_pdf():
    t = totals(all_rows(groups()))
    assert t["count"] == 39
    assert t["square_feet"] == 24_027_072
    assert close(t["original"], "1774432693.62")
    assert close(t["approved"], "549706168.28")
    assert close(t["pending"], "4533764.55")
    assert close(t["total_pcco"], "554239932.83")
    assert close(t["current"], "2328672626.44")


def test_region_subtotals_match_procore_pdf():
    by = {g.region: g.totals for g in groups()}
    assert [g.region for g in groups()] == ["HCS CALIFORNIA", "HCS MIDSOUTH", "HCS NORTHEAST", "HCS SOUTHEAST", "HCS TEXAS"]
    assert close(by["HCS CALIFORNIA"]["current"], "152132023.72")
    assert close(by["HCS MIDSOUTH"]["current"], "342659728.79")
    assert close(by["HCS NORTHEAST"]["current"], "323015373.20")
    assert close(by["HCS SOUTHEAST"]["current"], "154966218.82")
    assert close(by["HCS TEXAS"]["current"], "1355899281.91")
    assert by["HCS TEXAS"]["square_feet"] == 12_352_960


def test_row_order_matches_procore_pdf():
    tx = next(g for g in groups() if g.region == "HCS TEXAS")
    names = [r.name for r in tx.rows]
    assert names[:2] == ["Ranger 35 Commerce Center Bldg 1", "Medline BTS"]
    assert names.index("Westport 12 - Shell") < names.index("Project 10X")
    assert names[-1] == "Project Aero"


def test_blank_vs_zero_and_negatives():
    rows = {r.name: r for r in all_rows(groups())}
    assert rows["Strykers Road Warehouse"].approved is None      # blank in Procore
    assert rows["Goose Creek Phase 1, Bldg 1"].approved == 0     # $0.00 in Procore
    assert usd(rows["Napa Bldg. A - TikTok TI"].approved) == "($367,049.89)"


def test_owner_type_totals():
    segs = {s["label"]: s["totals"] for s in owner_segments(all_rows(groups()), CONFIG)}
    assert list(segs) == ["HIP", "Properties", "Third Party"]
    assert [segs[k]["count"] for k in segs] == [23, 11, 5]
    assert segs["HIP"]["current"] == D("1149773486.19")
    assert segs["Properties"]["current"] == D("599543859.17")
    assert segs["Third Party"]["current"] == D("579355281.09")
    # the three buckets must add back to the grand total
    grand = totals(all_rows(groups()))
    for col in ("original", "approved", "pending", "current"):
        assert sum(s[col] for s in segs.values()) == grand[col]


def test_texas_owner_subtotals():
    tx = next(g for g in groups() if g.region == "HCS TEXAS")
    segs = {s["label"]: s["totals"]["current"] for s in tx.segments(CONFIG)}
    assert segs == {"HIP": D("241829326.87"), "Properties": D("599543859.17"), "Third Party": D("514526095.87")}


def test_refuses_to_report_when_prime_contracts_are_missing():
    # Live check 2026-11-12: the service account could only see prime contracts on 2 of 39 projects.
    # The report must fail loudly rather than email execs a total that is missing most contracts.
    import pytest

    class PartialAccess(FixtureClient):
        def list_prime_contracts(self, project_id):
            return super().list_prime_contracts(project_id) if project_id % 10 == 0 else []

    with pytest.raises(RuntimeError, match="prime contract"):
        build_report(PartialAccess(ROOT / "tests/fixtures"), CONFIG)


def test_include_names_pins_the_report_to_the_export():
    assert len(CONFIG["filters"]["include_names"]) == 39
    assert {r.name for r in all_rows(groups())} == set(CONFIG["filters"]["include_names"])
