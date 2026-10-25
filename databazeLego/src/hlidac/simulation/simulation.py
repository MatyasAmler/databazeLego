"""Celá simulace: kmenová data, kalendář, zakázky, vážení a uložení do databáze."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional, Sequence

from hlidac.catalog import build_master_data
from hlidac.config import Settings
from hlidac.db import Database
from hlidac.repository import MasterDataRepository, OperationsRepository, clear_all
from hlidac.shifts import Rotation, ShiftCalendar
from hlidac.simulation.generator import RowIds, WeighingGenerator
from hlidac.simulation.planner import RunPlanner
from hlidac.simulation.scenarios import Scenario, default_scenarios


@dataclass(frozen=True)
class SimulationSummary:
    shifts: int
    runs: int
    weighings: int
    calibrations: int
    scenarios: Sequence[str]
    seconds: float


class Simulation:
    def __init__(self, settings: Settings, db: Database, scenarios: Optional[Sequence[Scenario]] = None) -> None:
        self.settings = settings
        self.db = db
        self.scenarios = list(scenarios) if scenarios is not None else default_scenarios(settings.timezone)

    def run(self) -> SimulationSummary:
        started = time.perf_counter()
        st = self.settings
        rng = random.Random(st.seed)  # stejný seed = stejná data (N4)

        master = build_master_data()
        calendar = ShiftCalendar(Rotation(anchor=st.sim_start), master.shift_types, master.crews, st.timezone)
        calendar.build(st.sim_start, st.sim_days)
        runs = RunPlanner(master, rng).plan(calendar.start, calendar.end)
        generator = WeighingGenerator(master, calendar, self.scenarios, rng)
        calibrations = [c for s in self.scenarios for c in s.calibrations()
                        if calendar.start <= c.calibrated_at < calendar.end]

        with self.db.connect() as conn:
            clear_all(conn)
            ids = MasterDataRepository(conn).save(master)
            ops = OperationsRepository(conn)
            shift_ids = ops.save_shifts(calendar.shifts, ids)
            run_ids = ops.save_runs(runs, ids)
            ops.save_calibrations(calibrations, ids)
            ops.create_partitions(st.sim_start, st.sim_start + timedelta(days=st.sim_days + 1))
            count = ops.copy_weighings(generator.generate(runs, RowIds(ids.scales, run_ids, shift_ids)))
            conn.execute("ANALYZE")

        return SimulationSummary(
            shifts=len(calendar.shifts),
            runs=len(runs),
            weighings=count,
            calibrations=len(calibrations),
            scenarios=[s.name for s in self.scenarios],
            seconds=time.perf_counter() - started,
        )
