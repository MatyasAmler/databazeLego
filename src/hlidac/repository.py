"""Ukládání a čtení dat z databáze."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Sequence

import psycopg
from psycopg.rows import dict_row

from hlidac.catalog import MasterData
from hlidac.domain import Alert, Calibration, ProductionRun, Shift, WeighingRow

COPY_CHUNK = 20_000


@dataclass
class IdMap:
    """Databázová id kmenových dat podle kódu."""

    lines: Dict[str, int] = field(default_factory=dict)
    scales: Dict[str, int] = field(default_factory=dict)
    elements: Dict[str, int] = field(default_factory=dict)
    products: Dict[str, int] = field(default_factory=dict)
    crews: Dict[str, int] = field(default_factory=dict)
    shift_types: Dict[str, int] = field(default_factory=dict)


def clear_all(conn: psycopg.Connection) -> None:
    """Smaže všechna data (kmenová i provozní), struktura tabulek zůstane."""
    conn.execute(
        "TRUNCATE alert, weighing, calibration, production_run, shift, product_element, "
        "product, element, scale, line, crew, shift_type RESTART IDENTITY CASCADE"
    )


class MasterDataRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def _insert(self, sql: str, params: Sequence) -> int:
        return self.conn.execute(sql, params).fetchone()[0]

    def save(self, master: MasterData) -> IdMap:
        ids = IdMap()
        for line in master.lines:
            ids.lines[line.code] = self._insert(
                "INSERT INTO line (code, name, nominal_speed_ppm) VALUES (%s, %s, %s) RETURNING line_id",
                (line.code, line.name, line.nominal_speed_ppm),
            )
        for s in master.scales:
            ids.scales[s.code] = self._insert(
                "INSERT INTO scale (code, serial_number, resolution_g, line_id) VALUES (%s, %s, %s, %s) RETURNING scale_id",
                (s.code, s.serial_number, s.resolution_g, ids.lines[s.line_code]),
            )
        for e in master.elements:
            ids.elements[e.element_no] = self._insert(
                "INSERT INTO element (element_no, name, weight_g) VALUES (%s, %s, %s) RETURNING element_id",
                (e.element_no, e.name, e.weight_g),
            )
        for p in master.products:
            pid = self._insert(
                "INSERT INTO product (product_no, name, film_weight_g) VALUES (%s, %s, %s) RETURNING product_id",
                (p.product_no, p.name, p.film_weight_g),
            )
            ids.products[p.product_no] = pid
            for c in p.components:
                self.conn.execute(
                    "INSERT INTO product_element (product_id, element_id, quantity) VALUES (%s, %s, %s)",
                    (pid, ids.elements[c.element.element_no], c.quantity),
                )
        for c in master.crews:
            ids.crews[c.code] = self._insert(
                "INSERT INTO crew (code, rotation_offset_days, description) VALUES (%s, %s, %s) RETURNING crew_id",
                (c.code, c.rotation_offset_days, c.description),
            )
        for t in master.shift_types:
            ids.shift_types[t.code] = self._insert(
                "INSERT INTO shift_type (code, name, start_time, duration_hours) VALUES (%s, %s, %s, %s) "
                "RETURNING shift_type_id",
                (t.code, t.name, t.start_time, t.duration_hours),
            )
        return ids


class OperationsRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def save_shifts(self, shifts: Sequence[Shift], ids: IdMap) -> List[int]:
        """Vrací id směn ve stejném pořadí, v jakém přišly."""
        out = []
        for s in shifts:
            out.append(
                self.conn.execute(
                    "INSERT INTO shift (shift_date, shift_type_id, crew_id, starts_at, ends_at) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING shift_id",
                    (s.shift_date, ids.shift_types[s.shift_type.code], ids.crews[s.crew.code], s.starts_at, s.ends_at),
                ).fetchone()[0]
            )
        return out

    def save_runs(self, runs: Sequence[ProductionRun], ids: IdMap) -> Dict[str, int]:
        out = {}
        for r in runs:
            out[r.run_no] = self.conn.execute(
                "INSERT INTO production_run (run_no, line_id, product_id, starts_at, ends_at, planned_qty) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING run_id",
                (r.run_no, ids.lines[r.line.code], ids.products[r.product.product_no], r.starts_at, r.ends_at, r.planned_qty),
            ).fetchone()[0]
        return out

    def save_calibrations(self, items: Sequence[Calibration], ids: IdMap) -> None:
        for c in items:
            self.conn.execute(
                "INSERT INTO calibration (scale_id, calibrated_at, offset_before_g, performed_by) VALUES (%s, %s, %s, %s)",
                (ids.scales[c.scale_code], c.calibrated_at, c.offset_before_g, c.performed_by),
            )

    def create_partitions(self, start: date, end: date) -> int:
        return self.conn.execute("SELECT create_weighing_partitions(%s, %s)", (start, end)).fetchone()[0]

    def copy_weighings(self, rows: Iterable[WeighingRow]) -> int:
        """Hromadný zápis přes COPY (řádově rychlejší než INSERT). Vrací počet řádků.

        Cizí klíče a vedlejší indexy se po dobu nahrávání odeberou a pak se vrátí
        (funkce z migrace 003). Vše běží v jedné transakci.
        """
        count = 0
        buf: List[str] = []
        self.conn.execute("SELECT weighing_bulk_load_begin()")
        with self.conn.cursor() as cur:
            with cur.copy("COPY weighing (scale_id, measured_at, run_id, shift_id, weight_g, result) FROM STDIN") as copy:
                for r in rows:
                    buf.append(f"{r.scale_id}\t{r.measured_at.isoformat()}\t{r.run_id}\t{r.shift_id}\t{r.weight_g}\t{r.result}\n")
                    if len(buf) >= COPY_CHUNK:
                        copy.write("".join(buf))
                        count += len(buf)
                        buf.clear()
                if buf:
                    copy.write("".join(buf))
                    count += len(buf)
        self.conn.execute("SELECT weighing_bulk_load_end()")
        return count


class AlertRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def replace(self, alerts: Sequence[Alert]) -> int:
        """Smaže předchozí upozornění a uloží nová (analýza běží vždy nad celým obdobím)."""
        self.conn.execute("DELETE FROM alert")
        for a in alerts:
            self.conn.execute(
                """
                INSERT INTO alert (alert_type, severity, line_id, scale_id, crew_id, valid_from, valid_to, message, details)
                VALUES (%s, %s,
                        (SELECT line_id FROM line WHERE code = %s),
                        (SELECT scale_id FROM scale WHERE code = %s),
                        (SELECT crew_id FROM crew WHERE code = %s),
                        %s, %s, %s, %s::jsonb)
                """,
                (
                    a.alert_type.value, a.severity.value, a.line_code, a.scale_code, a.crew_code,
                    a.valid_from, a.valid_to, a.message, json.dumps(a.details, ensure_ascii=False, default=str),
                ),
            )
        return len(alerts)

    def list(self) -> List[dict]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT a.alert_id, a.alert_type::text AS alert_type, a.severity::text AS severity,
                       l.code AS line_code, s.code AS scale_code, c.code AS crew_code,
                       a.valid_from, a.valid_to, a.message, a.details
                FROM alert a
                JOIN line l       ON l.line_id = a.line_id
                LEFT JOIN scale s ON s.scale_id = a.scale_id
                LEFT JOIN crew c  ON c.crew_id = a.crew_id
                ORDER BY a.valid_from, l.code
                """
            )
            return cur.fetchall()
