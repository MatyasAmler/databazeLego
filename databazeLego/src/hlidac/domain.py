"""Doménový model - odpovídá entitám konceptuálního modelu (docs/02_konceptualni_model.md)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any, Dict, NamedTuple, Optional, Tuple

CENT = Decimal("0.01")


class WeighingResult(str, Enum):
    OK = "OK"
    UNDER = "UNDER"
    OVER = "OVER"


class AlertType(str, Enum):
    SCALE_DRIFT = "SCALE_DRIFT"
    CREW_QUALITY = "CREW_QUALITY"
    CHANGEOVER_RAMPUP = "CHANGEOVER_RAMPUP"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class Line:
    code: str
    name: str
    nominal_speed_ppm: int


@dataclass(frozen=True)
class Scale:
    code: str
    serial_number: str
    resolution_g: Decimal
    line_code: str


@dataclass(frozen=True)
class Element:
    element_no: str
    name: str
    weight_g: Decimal


@dataclass(frozen=True)
class ProductComponent:
    element: Element
    quantity: int


@dataclass(frozen=True)
class Product:
    product_no: str
    name: str
    film_weight_g: Decimal
    components: Tuple[ProductComponent, ...]

    def target_weight_g(self) -> Decimal:
        """IO1: součet dílků + fólie, zaokrouhleno na 0,01 g (stejně jako v_product_spec)."""
        total = sum((c.element.weight_g * c.quantity for c in self.components), Decimal(0))
        return (total + self.film_weight_g).quantize(CENT, ROUND_HALF_UP)

    def tolerance_g(self) -> Decimal:
        """IO2: polovina hmotnosti nejlehčího dílku v sáčku."""
        lightest = min(c.element.weight_g for c in self.components)
        return (lightest / 2).quantize(CENT, ROUND_HALF_UP)


@dataclass(frozen=True)
class Crew:
    code: str
    rotation_offset_days: int
    description: str = ""


@dataclass(frozen=True)
class ShiftType:
    code: str
    name: str
    start_time: time
    duration_hours: int


@dataclass(frozen=True)
class Shift:
    shift_date: date
    shift_type: ShiftType
    crew: Crew
    starts_at: datetime
    ends_at: datetime

    def contains(self, ts: datetime) -> bool:
        # porovnání přes unixový čas: u stejného pásma by Python porovnával „nástěnný“ čas
        return self.starts_at.timestamp() <= ts.timestamp() < self.ends_at.timestamp()

    @property
    def duration_hours(self) -> float:
        return (self.ends_at.timestamp() - self.starts_at.timestamp()) / 3600


@dataclass(frozen=True)
class ProductionRun:
    run_no: str
    line: Line
    product: Product
    starts_at: datetime
    ends_at: datetime
    planned_qty: int

    def minutes_since_start(self, ts: datetime) -> float:
        return (ts - self.starts_at).total_seconds() / 60.0


@dataclass(frozen=True)
class Calibration:
    scale_code: str
    calibrated_at: datetime
    offset_before_g: Decimal
    performed_by: str


class WeighingRow(NamedTuple):
    """Jedno vážení. NamedTuple místo třídy: vzniknou jich miliony."""

    scale_id: int
    measured_at: datetime
    run_id: int
    shift_id: int
    weight_g: Decimal
    result: str


@dataclass
class Alert:
    alert_type: AlertType
    severity: Severity
    line_code: str
    valid_from: datetime
    message: str
    valid_to: Optional[datetime] = None
    scale_code: Optional[str] = None
    crew_code: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
