"""Spuštění analýzy: obnoví souhrny, pustí detektory a uloží upozornění."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Sequence

from hlidac.analysis.base import Detector
from hlidac.analysis.crew import CrewQualityDetector
from hlidac.analysis.drift import ScaleDriftDetector
from hlidac.analysis.rampup import RampupDetector
from hlidac.db import Database
from hlidac.domain import Alert
from hlidac.repository import AlertRepository


def default_detectors() -> List[Detector]:
    return [ScaleDriftDetector(), CrewQualityDetector(), RampupDetector()]


@dataclass(frozen=True)
class AnalysisResult:
    alerts: List[Alert]
    seconds: float


class AnalysisService:
    def __init__(self, db: Database, detectors: Optional[Sequence[Detector]] = None) -> None:
        self.db = db
        self.detectors = list(detectors) if detectors is not None else default_detectors()

    def run(self) -> AnalysisResult:
        started = time.perf_counter()
        with self.db.connect() as conn:
            conn.execute("REFRESH MATERIALIZED VIEW mv_hourly_stats")
            conn.execute("ANALYZE mv_hourly_stats")
            alerts: List[Alert] = []
            for detector in self.detectors:
                alerts.extend(detector.detect(conn))
            AlertRepository(conn).replace(alerts)
        return AnalysisResult(alerts=alerts, seconds=time.perf_counter() - started)
