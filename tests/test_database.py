"""Integrační testy proti PostgreSQL (vlastní databáze hlidac_test).

Spuštění: docker compose up -d && pytest
Test nad celým obdobím: HLIDAC_FULL=1 pytest
"""
from datetime import datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from psycopg import errors

from conftest import full_run_enabled
from hlidac.analysis import AnalysisService
from hlidac.catalog import build_master_data
from hlidac.repository import MasterDataRepository
from hlidac.simulation import Simulation

pytestmark = pytest.mark.db


def test_product_spec_view_matches_python(test_db):
    master = build_master_data()
    with test_db.connect() as conn:
        MasterDataRepository(conn).save(master)
        rows = dict(
            (no, (target, tol))
            for no, target, tol in conn.execute("SELECT product_no, target_weight_g, tolerance_g FROM v_product_spec")
        )
    for p in master.products:
        assert rows[p.product_no] == (p.target_weight_g(), p.tolerance_g())


def _seed(conn):
    ids = MasterDataRepository(conn).save(build_master_data())
    return ids


def test_constraints_reject_invalid_data(test_db):
    t = datetime(2026, 10, 5, 6, 0).astimezone()
    with test_db.connect() as conn:
        ids = _seed(conn)
        line, product = ids.lines["PP-01"], ids.products["S-2001"]
        conn.execute(
            "INSERT INTO production_run (run_no, line_id, product_id, starts_at, ends_at, planned_qty) "
            "VALUES ('Z1', %s, %s, %s, %s, 100)", (line, product, t, t + timedelta(hours=5)))
        checks = [
            # IO5: zakázky na lince se nepřekrývají
            (errors.ExclusionViolation,
             "INSERT INTO production_run (run_no, line_id, product_id, starts_at, ends_at, planned_qty) "
             "VALUES ('Z2', %s, %s, %s, %s, 100)", (line, product, t + timedelta(hours=4), t + timedelta(hours=8))),
            # 1:1 linka-váha
            (errors.UniqueViolation,
             "INSERT INTO scale (code, serial_number, resolution_g, line_id) VALUES ('CW-999', 'X', 0.01, %s)", (line,)),
            # IO8: počet dílků >= 1
            (errors.CheckViolation,
             "INSERT INTO product_element (product_id, element_id, quantity) VALUES (%s, %s, 0)",
             (product, ids.elements["D-1018"])),
            # IO10: upozornění na drift musí mít váhu
            (errors.CheckViolation,
             "INSERT INTO alert (alert_type, severity, line_id, valid_from, message) "
             "VALUES ('SCALE_DRIFT', 'WARNING', %s, now(), 'x')", (line,)),
        ]
        for exc, sql, params in checks:
            with pytest.raises(exc):
                with conn.transaction():
                    conn.execute(sql, params)
        # IO6: směny se nepřekrývají
        conn.execute("INSERT INTO shift (shift_date, shift_type_id, crew_id, starts_at, ends_at) "
                     "VALUES ('2026-10-05', %s, %s, %s, %s)",
                     (ids.shift_types["D"], ids.crews["A"], t, t + timedelta(hours=12)))
        with pytest.raises(errors.ExclusionViolation):
            with conn.transaction():
                conn.execute("INSERT INTO shift (shift_date, shift_type_id, crew_id, starts_at, ends_at) "
                             "VALUES ('2026-10-06', %s, %s, %s, %s)",
                             (ids.shift_types["N"], ids.crews["D"], t + timedelta(hours=11), t + timedelta(hours=23)))


@pytest.fixture()
def small_run(test_db, test_settings):
    st = test_settings.with_overrides(sim_days=2)
    summary = Simulation(st, test_db).run()
    return test_db, summary


def test_small_simulation_is_consistent(small_run):
    db, summary = small_run
    assert summary.weighings > 800_000  # 8 linek x 2 dny x 2 400 sáčků/h x ≈ 94 % času
    with db.connect() as conn:
        q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        assert q("SELECT count(*) FROM weighing") == summary.weighings
        # IO3: výsledek odpovídá toleranci výrobku
        assert q("""
            SELECT count(*) FROM weighing w
            JOIN production_run r USING (run_id) JOIN v_product_spec ps USING (product_id)
            WHERE w.result <> CASE WHEN w.weight_g - ps.target_weight_g < -ps.tolerance_g THEN 'UNDER'
                                   WHEN w.weight_g - ps.target_weight_g >  ps.tolerance_g THEN 'OVER'
                                   ELSE 'OK' END::weighing_result""") == 0
        # IO4: vážení leží uvnitř zakázky i směny
        assert q("""
            SELECT count(*) FROM weighing w
            JOIN production_run r USING (run_id) JOIN shift s USING (shift_id)
            WHERE NOT (w.measured_at >= r.starts_at AND w.measured_at < r.ends_at
                   AND w.measured_at >= s.starts_at AND w.measured_at < s.ends_at)""") == 0
        # vážení je na váze linky, na které běží zakázka
        assert q("""
            SELECT count(*) FROM weighing w JOIN production_run r USING (run_id) JOIN scale sc ON sc.scale_id = w.scale_id
            WHERE sc.line_id <> r.line_id""") == 0
        # oddíly: data jsou v denních oddílech, výchozí oddíl je prázdný
        assert q("SELECT count(*) FROM weighing_default") == 0
        assert q("SELECT count(*) FROM pg_inherits WHERE inhparent = 'weighing'::regclass") >= 3
        # cizí klíče se po hromadném nahrání vrátily
        assert q("SELECT count(*) FROM pg_constraint WHERE conrelid = 'weighing'::regclass AND contype = 'f'") == 3


def test_weighing_shift_consistency(small_run):
    """Řízená denormalizace weighing.shift_id odpovídá času vážení."""
    db, _ = small_run
    with db.connect() as conn:
        bad = conn.execute("""
            SELECT count(*) FROM weighing w
            WHERE w.shift_id <> (SELECT s.shift_id FROM shift s
                                 WHERE w.measured_at >= s.starts_at AND w.measured_at < s.ends_at)""").fetchone()[0]
    assert bad == 0


def test_analysis_runs_on_small_data(small_run):
    db, _ = small_run
    result = AnalysisService(db).run()
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM alert").fetchone()[0] == len(result.alerts)
        assert conn.execute("SELECT count(*) FROM mv_hourly_stats").fetchone()[0] > 0


@pytest.mark.slow
@pytest.mark.skipif(not full_run_enabled(), reason="spouští se s HLIDAC_FULL=1")
def test_full_period_finds_exactly_the_three_situations(test_db, test_settings):
    Simulation(test_settings, test_db).run()
    alerts = AnalysisService(test_db).run().alerts
    found = sorted((a.alert_type.value, a.line_code, a.scale_code, a.crew_code) for a in alerts)
    assert found == [
        ("CHANGEOVER_RAMPUP", "PP-03", None, None),
        ("CREW_QUALITY", "PP-07", None, "C"),
        ("SCALE_DRIFT", "PP-05", "CW-105", None),
    ]
    drift = next(a for a in alerts if a.alert_type.value == "SCALE_DRIFT")
    assert drift.details["lead_time_hours"] >= 2  # akceptační kritérium 3
    crew = next(a for a in alerts if a.alert_type.value == "CREW_QUALITY")
    assert crew.details["shift_type"] == "N"
    assert crew.details["same_crew_other_shift_type_rate"] < 0.005  # ve dne je parta v normálu
