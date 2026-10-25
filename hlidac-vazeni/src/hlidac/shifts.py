"""Rotace 2-2-4 a směnový kalendář.

Rotace: každá parta slouží 2 denní směny, 2 noční směny a pak má 4 dny volna (cyklus 8 dní).
Party jsou v cyklu posunuté o 2 dny, takže každou směnu slouží právě jedna parta.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, datetime, timedelta
from typing import List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from hlidac.domain import Crew, Shift, ShiftType


class Rotation:
    def __init__(
        self,
        anchor: date,
        cycle_days: int = 8,
        day_slots: Tuple[int, ...] = (0, 1),
        night_slots: Tuple[int, ...] = (2, 3),
    ) -> None:
        self.anchor = anchor  # den, kdy má parta s posunem 0 první denní směnu
        self.cycle_days = cycle_days
        self.slots = {"D": day_slots, "N": night_slots}

    def phase(self, day: date, crew: Crew) -> int:
        return ((day - self.anchor).days - crew.rotation_offset_days) % self.cycle_days

    def crew_for(self, day: date, shift_type_code: str, crews: Sequence[Crew]) -> Crew:
        """IO7: parta, která v daný den slouží danou směnu."""
        matches = [c for c in crews if self.phase(day, c) in self.slots[shift_type_code]]
        if len(matches) != 1:
            raise ValueError(f"Rotace nedává právě jednu partu pro {day} {shift_type_code}: {matches}")
        return matches[0]


class ShiftCalendar:
    def __init__(self, rotation: Rotation, shift_types: Sequence[ShiftType], crews: Sequence[Crew], timezone: str) -> None:
        self.rotation = rotation
        self.shift_types = sorted(shift_types, key=lambda t: t.start_time)
        self.crews = list(crews)
        self.tz = ZoneInfo(timezone)
        self.shifts: List[Shift] = []
        self._starts: List[float] = []  # začátky jako unixový čas (správně i přes změnu času)

    def build(self, start: date, days: int) -> List[Shift]:
        """Směny pro dny <start, start + days). Začátek i konec se počítají v místním čase,
        takže při změně času má noční směna správně 11 nebo 13 hodin."""
        shifts: List[Shift] = []
        for d in range(days):
            day = start + timedelta(days=d)
            for st in self.shift_types:
                local_start = datetime.combine(day, st.start_time)
                local_end = local_start + timedelta(hours=st.duration_hours)
                shifts.append(
                    Shift(
                        shift_date=day,
                        shift_type=st,
                        crew=self.rotation.crew_for(day, st.code, self.crews),
                        starts_at=local_start.replace(tzinfo=self.tz),
                        ends_at=local_end.replace(tzinfo=self.tz),
                    )
                )
        shifts.sort(key=lambda s: s.starts_at.timestamp())
        self.shifts = shifts
        self._starts = [s.starts_at.timestamp() for s in shifts]
        return shifts

    def shift_at(self, ts: datetime) -> Optional[Shift]:
        return self.shift_at_epoch(ts.timestamp())

    def shift_index_at_epoch(self, epoch: float) -> int:
        """Index směny v kalendáři pro unixový čas, nebo -1."""
        i = bisect_right(self._starts, epoch) - 1
        if i >= 0 and epoch < self.shifts[i].ends_at.timestamp():
            return i
        return -1

    def shift_at_epoch(self, epoch: float) -> Optional[Shift]:
        i = self.shift_index_at_epoch(epoch)
        return self.shifts[i] if i >= 0 else None

    @property
    def start(self) -> datetime:
        return self.shifts[0].starts_at

    @property
    def end(self) -> datetime:
        return self.shifts[-1].ends_at
