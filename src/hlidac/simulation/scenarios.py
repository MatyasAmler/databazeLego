"""Schované problémy S1-S3 (viz docs/01_zadani.md).

Každý scénář může upravit tři věci: o kolik váha měří vedle, pravděpodobnost chybějícího
dílku a pravděpodobnost přebývajícího dílku. Generátor se scénářů ptá jednou za minutu výroby.
"""
from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List
from zoneinfo import ZoneInfo

from hlidac.domain import Calibration


@dataclass(frozen=True)
class WeighingContext:
    line_code: str
    scale_code: str
    crew_code: str
    shift_type_code: str
    ts: datetime
    minutes_since_run_start: float


class Scenario(ABC):
    name: str = "scénář"

    def scale_offset_g(self, ctx: WeighingContext) -> float:
        """O kolik gramů váha v daný okamžik měří víc (+) nebo míň (−)."""
        return 0.0

    def missing_rate(self, ctx: WeighingContext, base: float) -> float:
        """Pravděpodobnost, že v sáčku chybí dílek."""
        return base

    def extra_rate(self, ctx: WeighingContext, base: float) -> float:
        """Pravděpodobnost, že v sáčku dílek přebývá."""
        return base

    def calibrations(self) -> List[Calibration]:
        return []


class ScaleDriftScenario(Scenario):
    """S1 - váha se postupně rozkalibruje a měří čím dál víc, dokud ji někdo nezkalibruje."""

    def __init__(self, scale_code: str, start: datetime, calibrated_at: datetime, rate_g_per_hour: float) -> None:
        self.name = f"Posun kalibrace {scale_code}"
        self.scale_code = scale_code
        self.start = start
        self.calibrated_at = calibrated_at
        self.rate_g_per_hour = rate_g_per_hour
        self._start_epoch = start.timestamp()
        self._end_epoch = calibrated_at.timestamp()

    def scale_offset_g(self, ctx: WeighingContext) -> float:
        if ctx.scale_code != self.scale_code:
            return 0.0
        t = ctx.ts.timestamp()
        if self._start_epoch <= t < self._end_epoch:
            return (t - self._start_epoch) / 3600.0 * self.rate_g_per_hour
        return 0.0

    def calibrations(self) -> List[Calibration]:
        hours = (self._end_epoch - self._start_epoch) / 3600.0
        offset = Decimal(str(round(hours * self.rate_g_per_hour, 3)))
        return [Calibration(self.scale_code, self.calibrated_at, offset, "Metrologie")]


class CrewQualityScenario(Scenario):
    """S2 - jedna parta má na jedné lince a jednom typu směny víc sáčků s chybějícím dílkem."""

    def __init__(self, line_code: str, crew_code: str, shift_type_code: str, missing_rate: float) -> None:
        self.name = f"Parta {crew_code} na {line_code} ({shift_type_code})"
        self.line_code = line_code
        self.crew_code = crew_code
        self.shift_type_code = shift_type_code
        self.rate = missing_rate

    def missing_rate(self, ctx: WeighingContext, base: float) -> float:
        if (ctx.line_code, ctx.crew_code, ctx.shift_type_code) == (self.line_code, self.crew_code, self.shift_type_code):
            return max(base, self.rate)
        return base


class ChangeoverRampupScenario(Scenario):
    """S3 - po přestavbě se linka rozbíhá déle a s vyšším výmětem než ostatní linky."""

    MISSING_SHARE = 0.7  # při rozběhu častěji chybí dílek, než přebývá

    def __init__(self, line_code: str, minutes: int, reject_rate: float) -> None:
        self.name = f"Rozběh po přestavbě {line_code}"
        self.line_code = line_code
        self.minutes = minutes
        self.reject_rate = reject_rate

    def _active(self, ctx: WeighingContext) -> bool:
        return ctx.line_code == self.line_code and ctx.minutes_since_run_start < self.minutes

    def missing_rate(self, ctx: WeighingContext, base: float) -> float:
        return max(base, self.reject_rate * self.MISSING_SHARE) if self._active(ctx) else base

    def extra_rate(self, ctx: WeighingContext, base: float) -> float:
        return max(base, self.reject_rate * (1 - self.MISSING_SHARE)) if self._active(ctx) else base


def default_scenarios(timezone: str) -> List[Scenario]:
    """Tři situace S1-S3 přesně podle zadání."""
    tz = ZoneInfo(timezone)
    return [
        ScaleDriftScenario(
            scale_code="CW-105",
            start=datetime(2026, 10, 12, 8, 0, tzinfo=tz),
            calibrated_at=datetime(2026, 10, 13, 22, 0, tzinfo=tz),
            rate_g_per_hour=0.010,
        ),
        CrewQualityScenario(line_code="PP-07", crew_code="C", shift_type_code="N", missing_rate=0.020),
        ChangeoverRampupScenario(line_code="PP-03", minutes=20, reject_rate=0.08),
    ]
