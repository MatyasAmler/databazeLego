"""Odvozené atributy výrobku (IO1, IO2) a plán zakázek (IO5)."""
import random
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from hlidac.catalog import build_master_data
from hlidac.simulation.planner import RunPlanner


def test_target_weight_and_tolerance():
    master = build_master_data()
    p = master.product("S-2002")
    # 6x1,05 + 10x0,55 + 12x0,36 + 6x0,72 + 2x1,62 + fólie 1,20
    assert p.target_weight_g() == Decimal("24.88")
    assert p.tolerance_g() == Decimal("0.18")  # polovina nejlehčího dílku (0,36 g)


def test_tolerance_rounds_half_up():
    master = build_master_data()
    assert master.product("S-2001").tolerance_g() == Decimal("0.23")  # 0,45 / 2 = 0,225


def test_tolerance_catches_missing_lightest_element():
    for p in build_master_data().products:
        lightest = min(c.element.weight_g for c in p.components)
        assert p.tolerance_g() < lightest


def test_runs_do_not_overlap_and_changeovers_fit():
    master = build_master_data()
    tz = ZoneInfo("Europe/Prague")
    start = datetime(2026, 10, 5, 6, 0, tzinfo=tz)
    end = start + timedelta(days=4)
    runs = RunPlanner(master, random.Random(1)).plan(start, end)
    for line in master.lines:
        own = sorted((r for r in runs if r.line == line), key=lambda r: r.starts_at)
        assert own[0].starts_at == start
        for a, b in zip(own, own[1:]):
            gap = (b.starts_at - a.ends_at).total_seconds() / 60
            assert 20 <= gap <= 40, "přestavba trvá 20-40 minut"
            assert a.product != b.product, "po sobě jdou různé výrobky"
            hours = (a.ends_at - a.starts_at).total_seconds() / 3600
            assert 4 <= hours <= 10
        for r in own:
            assert r.starts_at.second == 0 and r.ends_at <= end
            assert r.product.product_no in master.line_products[line.code]
