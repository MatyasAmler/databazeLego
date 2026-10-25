"""Generátor vážení a scénáře - bez databáze."""
import random
import statistics
from datetime import date, datetime
from itertools import islice
from zoneinfo import ZoneInfo

import pytest

from hlidac.catalog import build_master_data
from hlidac.shifts import Rotation, ShiftCalendar
from hlidac.simulation.generator import RowIds, WeighingGenerator
from hlidac.simulation.planner import RunPlanner
from hlidac.simulation.scenarios import CrewQualityScenario, ScaleDriftScenario

TZ = ZoneInfo("Europe/Prague")


def setup(scenarios, days=2, seed=7):
    master = build_master_data()
    cal = ShiftCalendar(Rotation(anchor=date(2026, 10, 5)), master.shift_types, master.crews, "Europe/Prague")
    cal.build(date(2026, 10, 5), days)
    rng = random.Random(seed)
    runs = RunPlanner(master, rng).plan(cal.start, cal.end)
    ids = RowIds(
        scales={s.code: i for i, s in enumerate(master.scales, 1)},
        runs={r.run_no: i for i, r in enumerate(runs, 1)},
        shifts=list(range(1, len(cal.shifts) + 1)),
    )
    return master, cal, runs, ids, WeighingGenerator(master, cal, scenarios, rng)


def test_same_seed_gives_same_data():
    def first_rows():
        master, cal, runs, ids, gen = setup([])
        return list(islice(gen.generate(runs, ids), 2000))

    assert first_rows() == first_rows()


def test_result_matches_tolerance_rule():
    master, cal, runs, ids, gen = setup([], days=1)
    spec = {ids.runs[r.run_no]: (r.product.target_weight_g(), r.product.tolerance_g()) for r in runs}
    for row in islice(gen.generate(runs, ids), 200_000):
        target, tol = spec[row.run_id]
        dev = row.weight_g - target
        expected = "UNDER" if dev < -tol else "OVER" if dev > tol else "OK"
        assert row.result == expected


def test_timestamps_increase_and_shift_ids_match_calendar():
    master, cal, runs, ids, gen = setup([], days=1)
    last = {}
    for row in islice(gen.generate(runs, ids), 100_000):
        assert row.measured_at > last.get(row.scale_id, datetime.min.replace(tzinfo=TZ))
        last[row.scale_id] = row.measured_at
        assert cal.shifts[row.shift_id - 1].contains(row.measured_at)


def test_base_reject_rate_is_realistic():
    master, cal, runs, ids, gen = setup([], days=1)
    rows = list(islice(gen.generate(runs, ids), 300_000))
    rate = sum(r.result != "OK" for r in rows) / len(rows)
    assert 0.002 < rate < 0.008


def test_scale_drift_moves_measured_weight():
    start = datetime(2026, 10, 5, 12, 0, tzinfo=TZ)
    drift = ScaleDriftScenario("CW-101", start, datetime(2026, 10, 6, 6, 0, tzinfo=TZ), rate_g_per_hour=0.05)
    master, cal, runs, ids, gen = setup([drift], days=1)
    spec = {ids.runs[r.run_no]: float(r.product.target_weight_g()) for r in runs}
    before, after = [], []
    for row in gen.generate(runs, ids):
        if row.scale_id != 1 or row.result != "OK":
            continue
        dev = float(row.weight_g) - spec[row.run_id]
        if row.measured_at < start:
            before.append(dev)
        elif row.measured_at.hour in (15, 16):  # 3-5 h po začátku posunu = +0,15 až +0,25 g
            after.append(dev)
    assert statistics.fmean(after) - statistics.fmean(before) > 0.1
    assert drift.calibrations()[0].offset_before_g > 0


def test_crew_scenario_only_affects_its_crew_and_shift_type():
    # 5. 10. má noční směnu parta D (posun 6)
    scenario = CrewQualityScenario("PP-01", "D", "N", missing_rate=0.2)
    master, cal, runs, ids, gen = setup([scenario], days=1)
    scale_id = ids.scales["CW-101"]
    night = [r for r in gen.generate(runs, ids) if r.scale_id == scale_id]
    night_rate = statistics.fmean(r.result == "UNDER" for r in night if r.measured_at.hour >= 18 or r.measured_at.hour < 6)
    day_rate = statistics.fmean(r.result == "UNDER" for r in night if 6 <= r.measured_at.hour < 18)
    assert night_rate > 0.15
    assert day_rate < 0.02
