"""Měření výkonu dotazů pro docs/06_vysledky.md.

Spuštění (po `python -m hlidac all`): python scripts/benchmark.py
"""
from __future__ import annotations

import json
import re
import statistics
import time

import psycopg

from hlidac.config import Settings

QUERIES = {
    "Výmět podle party a typu směny - přímo z vážení": """
        SELECT c.code, st.code, count(*) FILTER (WHERE w.result = 'UNDER')::numeric / count(*)
        FROM weighing w JOIN shift s USING (shift_id) JOIN crew c USING (crew_id)
        JOIN shift_type st USING (shift_type_id) GROUP BY c.code, st.code""",
    "Výmět podle party a typu směny - z hodinových souhrnů": """
        SELECT c.code, st.code, sum(h.n_under)::numeric / sum(h.n)
        FROM mv_hourly_stats h JOIN shift s USING (shift_id) JOIN crew c USING (crew_id)
        JOIN shift_type st USING (shift_type_id) GROUP BY c.code, st.code""",
    "Jedna váha, 6 hodin (regulační diagram)": """
        SELECT date_trunc('hour', measured_at), avg(weight_g), count(*) FROM weighing
        WHERE scale_id = (SELECT scale_id FROM scale WHERE code = 'CW-105')
          AND measured_at >= '2026-10-12 08:00+02' AND measured_at < '2026-10-12 14:00+02'
        GROUP BY 1""",
    "Všechny váhy, jeden den": """
        SELECT scale_id, count(*) FROM weighing
        WHERE measured_at >= '2026-10-12 00:00+02' AND measured_at < '2026-10-13 00:00+02' GROUP BY 1""",
}


def explain(conn, sql):
    times, plan = [], None
    for _ in range(3):
        plan = conn.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql).fetchone()[0][0]
        times.append(plan["Execution Time"])
    partitions = set(re.findall(r'"Relation Name": "(weighing_\d+|weighing_default)"', json.dumps(plan)))
    return statistics.median(times), len(partitions)


def main() -> None:
    st = Settings.from_env()
    with psycopg.connect(st.database_url, options=f"-c timezone={st.timezone}") as conn:
        q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        print(f"Vážení: {q('SELECT count(*) FROM weighing'):,}".replace(",", " "))
        for name, sql in QUERIES.items():
            ms, parts = explain(conn, sql)
            print(f"{name}: {ms:.1f} ms (čtené oddíly: {parts})")
        conn.execute("SET max_parallel_workers_per_gather = 0")
        ms, _ = explain(conn, list(QUERIES.values())[0])
        print(f"Přímo z vážení bez paralelismu: {ms:.1f} ms")
        conn.execute("RESET max_parallel_workers_per_gather")
        size = "SELECT pg_size_pretty(sum({f}(inhrelid))) FROM pg_inherits WHERE inhparent = 'weighing'::regclass"
        print("Tabulka vážení:", q(size.format(f="pg_relation_size")), "| s indexy:", q(size.format(f="pg_total_relation_size")))
        started = time.perf_counter()
        conn.execute("REFRESH MATERIALIZED VIEW mv_hourly_stats")
        print(f"Obnovení hodinových souhrnů: {time.perf_counter() - started:.1f} s, "
              f"{q('SELECT count(*) FROM mv_hourly_stats')} řádků")


if __name__ == "__main__":
    main()
