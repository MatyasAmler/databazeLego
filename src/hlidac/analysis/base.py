"""Společné rozhraní detektorů a pomocné funkce pro české texty upozornění."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List

import psycopg

from hlidac.domain import Alert

NBSP = " "  # nezlomitelná mezera mezi číslem a jednotkou
MINUS = "−"


class Detector(ABC):
    name: str = "detektor"

    @abstractmethod
    def detect(self, conn: psycopg.Connection) -> List[Alert]:
        """Projde data v databázi a vrátí nalezená upozornění."""


def _num(x: float, digits: int, sign: bool = False) -> str:
    s = f"{x:+.{digits}f}" if sign else f"{x:.{digits}f}"
    return s.replace(".", ",").replace("-", MINUS)


def pct(x: float, digits: int = 1) -> str:
    """0.0213 -> '2,1 %'."""
    return _num(x * 100, digits) + NBSP + "%"


def pp(x: float, digits: int = 1) -> str:
    """Rozdíl podílů v procentních bodech: 0.076 -> '7,6 p. b.'."""
    return _num(x * 100, digits) + NBSP + "p." + NBSP + "b."


def grams(x: float, digits: int = 2, sign: bool = True) -> str:
    """0.26 -> '+0,26 g'."""
    return _num(x, digits, sign) + NBSP + "g"


def times(x: float) -> str:
    """7.84 -> '7,8x'."""
    return _num(x, 1) + "x"


def count(n: int) -> str:
    """12345 -> '12 345'."""
    return f"{n:,}".replace(",", NBSP)


def hours(x: float) -> str:
    return _num(x, 1) + NBSP + "h"


def when(ts: datetime) -> str:
    """Datum a čas po česku: '12. 10. 10:00'."""
    return f"{ts.day}. {ts.month}. {ts:%H:%M}"
