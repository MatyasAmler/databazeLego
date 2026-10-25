"""Detekce posunu kalibrace váhy pomocí regulačních mezí (SPC).

Pro každou váhu se z období běžného provozu (baseline) spočítá průměr μ a směrodatná
odchylka σ hodinové průměrné odchylky dobrých sáčků. Když jsou aspoň dvě hodiny po sobě
mimo μ ± 3σ, váha se rozchází s cílem a je čas ji zkalibrovat.
"""
from __future__ import annotations

import statistics
from datetime import timedelta
from itertools import groupby
from typing import List, Optional

import psycopg
from psycopg.rows import namedtuple_row

from hlidac.analysis.base import Detector, count, grams, hours, pct, when
from hlidac.domain import Alert, AlertType, Severity


class ScaleDriftDetector(Detector):
    name = "Posun kalibrace váhy"

    def __init__(
        self,
        baseline_days: int = 4,
        sigma: float = 3.0,
        consecutive_hours: int = 2,
        min_ok_samples: int = 50,
        reject_alarm_rate: float = 0.01,
        max_gap_hours: int = 2,
    ) -> None:
        self.baseline_days = baseline_days
        self.sigma = sigma
        self.consecutive_hours = consecutive_hours
        self.min_ok_samples = min_ok_samples
        self.reject_alarm_rate = reject_alarm_rate
        self.max_gap = timedelta(hours=max_gap_hours)

    def detect(self, conn: psycopg.Connection) -> List[Alert]:
        with conn.cursor(row_factory=namedtuple_row) as cur:
            rows = cur.execute(
                "SELECT scale_code, line_code, hour, n, n_ok_steady, n_over, reject_rate, mean_dev_ok "
                "FROM v_scale_hourly ORDER BY scale_code, hour"
            ).fetchall()
            calibrations = cur.execute(
                "SELECT s.code AS scale_code, c.calibrated_at FROM calibration c JOIN scale s USING (scale_id)"
            ).fetchall()
        if not rows:
            return []
        baseline_end = min(r.hour for r in rows) + timedelta(days=self.baseline_days)
        alerts: List[Alert] = []

        for scale_code, group in groupby(rows, key=lambda r: r.scale_code):
            hours_ = list(group)
            base = [float(r.mean_dev_ok) for r in hours_
                    if r.hour < baseline_end and r.n_ok_steady >= self.min_ok_samples and r.mean_dev_ok is not None]
            if len(base) < 24:
                continue
            # TODO: meze pro každý výrobek zvlášť (teď jsou společné pro celou váhu)
            mu = statistics.fmean(base)
            sd = statistics.stdev(base)
            base_hours = [r for r in hours_ if r.hour < baseline_end]
            base_over_rate = float(sum(r.n_over for r in base_hours)) / max(1.0, float(sum(r.n for r in base_hours)))
            ucl, lcl = mu + self.sigma * sd, mu - self.sigma * sd

            # hodiny po baseline: je váha mimo regulační meze?
            points = []
            for r in hours_:
                if r.hour < baseline_end:
                    continue
                dev = float(r.mean_dev_ok) if r.mean_dev_ok is not None else None
                almost_all_rejected = float(r.reject_rate) >= 0.5
                if r.n_ok_steady >= self.min_ok_samples and dev is not None:
                    out = dev > ucl or dev < lcl
                elif almost_all_rejected:
                    out = True  # váha vyhazuje skoro všechno - silný signál
                else:
                    continue  # málo dat (přestavba)
                points.append((r, dev, out))

            for episode in self._episodes(points):
                alerts.append(self._alert(scale_code, episode, hours_, base_over_rate, mu, sd, ucl, lcl, calibrations))
        return alerts

    def _episodes(self, points):
        """Souvislé úseky hodin mimo meze (mezera bez dat do max_gap se toleruje)."""
        episodes, current, last = [], [], None
        for r, dev, out in points:
            if out and current and r.hour - last <= self.max_gap:
                current.append((r, dev))
            elif out:
                if len(current) >= self.consecutive_hours:
                    episodes.append(current)
                current = [(r, dev)]
            else:
                if len(current) >= self.consecutive_hours:
                    episodes.append(current)
                current = []
            last = r.hour
        if len(current) >= self.consecutive_hours:
            episodes.append(current)
        return episodes

    def _alert(self, scale_code, episode, all_hours, base_over_rate, mu, sd, ucl, lcl, calibrations) -> Alert:
        first, last = episode[0][0], episode[-1][0]
        detected_at = episode[self.consecutive_hours - 1][0].hour + timedelta(hours=1)
        devs = [d for _, d in episode if d is not None]
        peak = max(devs, key=abs) if devs else None
        direction = "víc" if (peak or 0) > 0 else "míň"
        valid_to = last.hour + timedelta(hours=1)

        first_reject: Optional[object] = next(
            (r for r, _ in episode if float(r.reject_rate) > self.reject_alarm_rate), None)
        lead_h = (first_reject.hour - detected_at).total_seconds() / 3600 if first_reject else None
        cal = next((c.calibrated_at for c in calibrations
                    if c.scale_code == scale_code and first.hour <= c.calibrated_at <= valid_to + timedelta(hours=2)), None)
        max_reject = max(float(r.reject_rate) for r, _ in episode)
        # nadváhy navíc proti běžnému stavu = sáčky, které váha vyřadila kvůli posunu (většinou dobré)
        window = [r for r in all_hours if first.hour <= r.hour < valid_to]
        extra_over = sum(max(0.0, float(r.n_over) - base_over_rate * float(r.n)) for r in window)
        saved = sum(max(0.0, float(r.n_over) - base_over_rate * float(r.n)) for r in window if r.hour >= detected_at)

        parts = [
            f"Váha {scale_code} ({first.line_code}) měří od {when(first.hour)} soustavně {direction}: "
            f"průměrná odchylka dobrých sáčků až {grams(peak)} (regulační meze {grams(lcl, 3)} až {grams(ucl, 3)})."
        ]
        if first_reject is not None and lead_h is not None and lead_h > 0:
            parts.append(
                f"Upozornění přišlo {when(detected_at)}, {hours(lead_h)} předtím, než výmět překročil "
                f"{pct(self.reject_alarm_rate, 0)} ({when(first_reject.hour)})."
            )
        parts.append(
            f"Nejvyšší hodinový výmět {pct(max_reject)}, celkem zhruba {count(int(extra_over))} sáčků vyřazených navíc "
            f"(většinou dobrých). Při kalibraci hned po upozornění by se jich ušetřilo zhruba {count(int(saved))}."
        )
        parts.append(f"Kalibrace {when(cal)} problém odstranila." if cal else "Doporučení: zkalibrovat váhu.")

        return Alert(
            alert_type=AlertType.SCALE_DRIFT,
            severity=Severity.CRITICAL if max_reject > self.reject_alarm_rate else Severity.WARNING,
            line_code=first.line_code,
            scale_code=scale_code,
            valid_from=first.hour,
            valid_to=valid_to,
            message=" ".join(parts),
            details={
                "baseline_mean_g": round(mu, 4),
                "baseline_sd_g": round(sd, 4),
                "ucl_g": round(ucl, 4),
                "lcl_g": round(lcl, 4),
                "detected_at": detected_at.isoformat(),
                "peak_dev_g": round(peak, 4) if peak is not None else None,
                "hours_out_of_control": len(episode),
                "first_hour_reject_over_limit": first_reject.hour.isoformat() if first_reject else None,
                "lead_time_hours": round(lead_h, 1) if lead_h is not None else None,
                "max_hourly_reject_rate": round(max_reject, 4),
                "extra_rejected_bags": int(extra_over),
                "bags_saved_if_acted_on_alert": int(saved),
                "calibrated_at": cal.isoformat() if cal else None,
            },
        )
