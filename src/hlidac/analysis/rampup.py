"""Detekce špatného rozběhu po přestavbě.

Pro každou linku se spočítá, o kolik je výmět v prvních 20 minutách zakázky vyšší než
v ustáleném provozu téže linky (nárůst při rozběhu). Ten se porovná s mediánem ostatních
linek. Díky porovnání s vlastním ustáleným provozem se linka s jiným problémem
(např. rozkalibrovaná váha) nehlásí jako problém rozběhu.
"""
from __future__ import annotations

import statistics
from typing import List

import psycopg
from psycopg.rows import namedtuple_row

from hlidac.analysis.base import Detector, count, pct, pp, times
from hlidac.domain import Alert, AlertType, Severity


class RampupDetector(Detector):
    name = "Rozběh po přestavbě"

    # TODO: window_minutes brát ze Settings.rampup_minutes, teď musí sedět s 002_analytics.sql
    def __init__(self, min_ratio: float = 3.0, min_excess: float = 0.03, window_minutes: int = 20) -> None:
        self.min_ratio = min_ratio
        self.min_excess = min_excess
        self.window_minutes = window_minutes

    def detect(self, conn: psycopg.Connection) -> List[Alert]:
        with conn.cursor(row_factory=namedtuple_row) as cur:
            rows = cur.execute(
                "SELECT v.line_code, v.runs, v.n_rampup, v.n_rampup_rejected, v.rampup_reject_rate, "
                "       v.steady_reject_rate, min(r.starts_at) AS first_start, max(r.ends_at) AS last_end "
                "FROM v_rampup_by_line v JOIN production_run r ON r.line_id = v.line_id "
                "GROUP BY v.line_code, v.runs, v.n_rampup, v.n_rampup_rejected, v.rampup_reject_rate, v.steady_reject_rate "
                "ORDER BY v.line_code"
            ).fetchall()
        excess = {r.line_code: float(r.rampup_reject_rate or 0) - float(r.steady_reject_rate or 0) for r in rows}
        steady = {r.line_code: float(r.steady_reject_rate or 0) for r in rows}
        alerts: List[Alert] = []
        for r in rows:
            others = [v for code, v in excess.items() if code != r.line_code]
            if not others:
                continue
            med = statistics.median(others)
            own = excess[r.line_code]
            ratio = own / med if med > 0 else float("inf")
            if own < self.min_excess or ratio < self.min_ratio:
                continue
            rampup_rate = float(r.rampup_reject_rate)
            extra = int(float(r.n_rampup) * (own - med))
            steady_others = statistics.median(v for code, v in steady.items() if code != r.line_code)
            steady_note = (
                f"V ustáleném provozu je linka v normálu ({pct(steady[r.line_code])})."
                if steady[r.line_code] <= 1.5 * steady_others
                else f"Pozor, i v ustáleném provozu má linka vyšší výmět ({pct(steady[r.line_code])})."
            )
            alerts.append(
                Alert(
                    alert_type=AlertType.CHANGEOVER_RAMPUP,
                    severity=Severity.WARNING,
                    line_code=r.line_code,
                    valid_from=r.first_start,
                    valid_to=r.last_end,
                    message=(
                        f"{r.line_code}: v prvních {self.window_minutes} minutách po přestavbě je výmět {pct(rampup_rate)}, "
                        f"o {pp(own)} víc než v ustáleném provozu. U ostatních linek je nárůst při rozběhu jen "
                        f"{pp(med)} (medián), tedy {times(ratio)} menší. Za {r.runs} zakázek to je zhruba "
                        f"{count(extra)} vyřazených sáčků navíc. {steady_note} "
                        f"Doporučení: projít postup přestavby a seřízení podavačů."
                    ),
                    details={
                        "rampup_reject_rate": round(rampup_rate, 5),
                        "steady_reject_rate": round(steady[r.line_code], 5),
                        "rampup_excess": round(own, 5),
                        "others_median_excess": round(med, 5),
                        "ratio": round(ratio, 2),
                        "runs": int(r.runs),
                        "extra_rejected_bags": extra,
                    },
                )
            )
        return alerts
