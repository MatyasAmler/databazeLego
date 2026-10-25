"""Plán zakázek: co se kdy na které lince balí a kdy jsou přestavby."""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import List

from hlidac.catalog import MasterData
from hlidac.domain import ProductionRun


class RunPlanner:
    MIN_RUN_HOURS = 4.0
    MAX_RUN_HOURS = 10.0
    MIN_CHANGEOVER_MIN = 20
    MAX_CHANGEOVER_MIN = 40
    MIN_LAST_RUN_MIN = 30  # kratší zbytek na konci období se už nezačíná
    PLAN_EFFICIENCY = 0.95

    def __init__(self, master: MasterData, rng: random.Random) -> None:
        self.master = master
        self.rng = rng

    def plan(self, start: datetime, end: datetime) -> List[ProductionRun]:
        runs: List[ProductionRun] = []
        for line_no, line in enumerate(self.master.lines, start=1):
            products = self.master.products_for_line(line.code)
            t = start
            previous = None
            seq = 0
            while (end - t).total_seconds() / 60 >= self.MIN_LAST_RUN_MIN:
                choices = [p for p in products if p is not previous] or products
                product = self.rng.choice(choices)
                # délka zakázky zaokrouhlená na 5 minut
                minutes = 5 * round(self.rng.uniform(self.MIN_RUN_HOURS, self.MAX_RUN_HOURS) * 12)
                run_end = min(t + timedelta(minutes=minutes), end)
                seq += 1
                run_minutes = (run_end - t).total_seconds() / 60
                runs.append(
                    ProductionRun(
                        run_no=f"Z{start:%y%m}-{line_no:02d}-{seq:03d}",
                        line=line,
                        product=product,
                        starts_at=t,
                        ends_at=run_end,
                        planned_qty=max(1, int(run_minutes * line.nominal_speed_ppm * self.PLAN_EFFICIENCY)),
                    )
                )
                previous = product
                t = run_end + timedelta(minutes=self.rng.randint(self.MIN_CHANGEOVER_MIN, self.MAX_CHANGEOVER_MIN))
        return runs
