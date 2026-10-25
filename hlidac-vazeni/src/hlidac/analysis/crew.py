"""Detekce problému party: podváha (chybějící dílek) jedné party proti ostatním partám
na stejné lince a stejném typu směny. Díky tomu jde odlišit problém party od problému noci."""
from __future__ import annotations

import statistics
from itertools import groupby
from typing import List

import psycopg
from psycopg.rows import namedtuple_row

from hlidac.analysis.base import Detector, pct, times, when
from hlidac.domain import Alert, AlertType, Severity

SHIFT_NAME = {"D": "denní", "N": "noční"}


class CrewQualityDetector(Detector):
    name = "Problém party"

    def __init__(self, min_ratio: float = 2.5, min_diff: float = 0.005, min_count: int = 10_000) -> None:
        self.min_ratio = min_ratio
        self.min_diff = min_diff
        self.min_count = min_count

    def detect(self, conn: psycopg.Connection) -> List[Alert]:
        with conn.cursor(row_factory=namedtuple_row) as cur:
            rows = cur.execute(
                "SELECT line_code, shift_type_code, crew_code, shifts, n_steady, n_under_steady, under_rate "
                "FROM v_quality_by_crew ORDER BY line_code, shift_type_code, crew_code"
            ).fetchall()
            periods = {
                (r.crew_code, r.shift_type_code): (r.first_start, r.last_end)
                for r in cur.execute(
                    "SELECT c.code AS crew_code, st.code AS shift_type_code, "
                    "       min(s.starts_at) AS first_start, max(s.ends_at) AS last_end "
                    "FROM shift s JOIN crew c USING (crew_id) JOIN shift_type st USING (shift_type_id) "
                    "GROUP BY c.code, st.code"
                )
            }
        rate = {(r.line_code, r.shift_type_code, r.crew_code): float(r.under_rate or 0) for r in rows}
        alerts: List[Alert] = []

        for (line, st), group in groupby(rows, key=lambda r: (r.line_code, r.shift_type_code)):
            group = list(group)
            for r in group:
                others = [float(o.under_rate or 0) for o in group if o.crew_code != r.crew_code]
                if not others or r.n_steady < self.min_count:
                    continue
                med = statistics.median(others)
                own = float(r.under_rate or 0)
                ratio = own / med if med > 0 else float("inf")
                if ratio < self.min_ratio or own - med < self.min_diff:
                    continue

                other_st = "D" if st == "N" else "N"
                own_other = rate.get((line, other_st, r.crew_code))
                others_other = [v for (l2, s2, c2), v in rate.items() if l2 == line and s2 == other_st and c2 != r.crew_code]
                med_other = statistics.median(others_other) if others_other else None
                normal_elsewhere = own_other is not None and med_other is not None and own_other <= 1.5 * med_other

                msg = (
                    f"{line}: parta {r.crew_code} má na {SHIFT_NAME[st]} směně {pct(own)} sáčků s chybějícím dílkem, "
                    f"ostatní party na {SHIFT_NAME[st]} směně {pct(med)} (medián), tedy {times(ratio)} víc."
                )
                if normal_elsewhere:
                    msg += (
                        f" Na {SHIFT_NAME[other_st]} směně je parta {r.crew_code} v normálu ({pct(own_other)}), "
                        f"takže nejde o problém {SHIFT_NAME[st]} směny obecně, ale o postup této party."
                    )
                msg += " Doporučení: projít s partou plnění zásobníků dílků."
                first, last = periods.get((r.crew_code, st), (None, None))
                alerts.append(
                    Alert(
                        alert_type=AlertType.CREW_QUALITY,
                        severity=Severity.CRITICAL if ratio >= 5 else Severity.WARNING,
                        line_code=line,
                        crew_code=r.crew_code,
                        valid_from=first,
                        valid_to=last,
                        message=msg,
                        details={
                            "shift_type": st,
                            "under_rate": round(own, 5),
                            "others_median": round(med, 5),
                            "ratio": round(ratio, 2),
                            "weighings": int(r.n_steady),
                            "shifts": int(r.shifts),
                            "same_crew_other_shift_type_rate": round(own_other, 5) if own_other is not None else None,
                            "first_shift": when(first) if first else None,
                        },
                    )
                )
        return alerts
