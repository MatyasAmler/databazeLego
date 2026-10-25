"""Rotace 2-2-4 a směnový kalendář (IO6, IO7)."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from hlidac.catalog import build_master_data
from hlidac.shifts import Rotation, ShiftCalendar

TZ = "Europe/Prague"
START = date(2026, 10, 5)


@pytest.fixture()
def master():
    return build_master_data()


def make_calendar(master, start=START, days=16):
    cal = ShiftCalendar(Rotation(anchor=START), master.shift_types, master.crews, TZ)
    cal.build(start, days)
    return cal


def test_each_crew_works_2_days_2_nights_then_4_off(master):
    rotation = Rotation(anchor=START)
    for crew in master.crews:
        pattern = []
        for d in range(8):
            day = START + timedelta(days=d)
            if rotation.crew_for(day, "D", master.crews) == crew:
                pattern.append("D")
            elif rotation.crew_for(day, "N", master.crews) == crew:
                pattern.append("N")
            else:
                pattern.append("-")
        # posunutý vzor D D N N - - - - (cyklicky)
        assert pattern.count("D") == 2 and pattern.count("N") == 2 and pattern.count("-") == 4
        doubled = "".join(pattern) * 2
        assert "DDNN----" in doubled, f"parta {crew.code}: {''.join(pattern)}"


def test_every_shift_has_exactly_one_crew(master):
    rotation = Rotation(anchor=START)
    for d in range(64):
        day = START + timedelta(days=d)
        day_crew = rotation.crew_for(day, "D", master.crews)
        night_crew = rotation.crew_for(day, "N", master.crews)
        assert day_crew != night_crew


def test_calendar_is_contiguous_12h_shifts(master):
    cal = make_calendar(master)
    assert len(cal.shifts) == 32
    first = cal.shifts[0]
    assert (first.starts_at.hour, first.shift_type.code) == (6, "D")
    for a, b in zip(cal.shifts, cal.shifts[1:]):
        assert a.ends_at.timestamp() == b.starts_at.timestamp()
        assert a.duration_hours == 12


def test_each_crew_has_4_day_and_4_night_shifts_in_16_days(master):
    cal = make_calendar(master)
    for crew in master.crews:
        own = [s for s in cal.shifts if s.crew == crew]
        assert sum(s.shift_type.code == "D" for s in own) == 4
        assert sum(s.shift_type.code == "N" for s in own) == 4


def test_night_shift_over_dst_change_is_13_hours(master):
    # 25. 10. 2026 ve 3:00 se posouvá čas zpět na 2:00
    cal = make_calendar(master, start=date(2026, 10, 24), days=1)
    night = [s for s in cal.shifts if s.shift_type.code == "N"][0]
    assert night.duration_hours == 13


def test_shift_at_boundaries(master):
    cal = make_calendar(master)
    tz = ZoneInfo(TZ)
    assert cal.shift_at(datetime(2026, 10, 6, 5, 59, 59, tzinfo=tz)).shift_type.code == "N"
    assert cal.shift_at(datetime(2026, 10, 6, 6, 0, 0, tzinfo=tz)).shift_type.code == "D"
    assert cal.shift_at(datetime(2026, 10, 5, 5, 0, tzinfo=tz)) is None  # před začátkem kalendáře
