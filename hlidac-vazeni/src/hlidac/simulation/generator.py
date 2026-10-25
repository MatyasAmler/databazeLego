"""Generátor jednotlivých vážení.

Model jednoho sáčku:
  naměřená hmotnost = cílová hmotnost + odchylka výrobku + posun váhy (scénář)
                      + náhodný rozptyl (váha, fólie, dílky)
                      − hmotnost dílku, pokud chybí / + hmotnost dílku, pokud přebývá
Výsledek (OK / UNDER / OVER) vyhodnotí „váha“ podle tolerance výrobku (IO3).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, Iterator, List, Sequence

from hlidac.catalog import MasterData
from hlidac.domain import Product, ProductionRun, WeighingRow
from hlidac.shifts import ShiftCalendar
from hlidac.simulation.scenarios import Scenario, WeighingContext

SCALE_NOISE_G = 0.025       # opakovatelnost váhy
FILM_NOISE_G = 0.015        # rozptyl hmotnosti fólie
ELEMENT_CV = 0.004          # rozptyl hmotnosti dílku (0,4 %)
BASE_MISSING_RATE = 0.0025  # běžně chybí dílek v 0,25 % sáčků
BASE_EXTRA_RATE = 0.0010    # běžně dílek přebývá v 0,10 % sáčků
BASE_RAMPUP_MINUTES = 10    # běžný rozběh po přestavbě
BASE_RAMPUP_REJECT = 0.02   # během běžného rozběhu 2 % výmět
JITTER_S = 0.25             # nepravidelnost taktu linky


@dataclass(frozen=True)
class RowIds:
    """Databázová id, která generátor potřebuje do řádků vážení."""

    scales: Dict[str, int]
    runs: Dict[str, int]
    shifts: List[int]  # ve stejném pořadí jako ShiftCalendar.shifts


@dataclass(frozen=True)
class _ProductModel:
    target: float
    target_c: int  # v setinách gramu
    tol_c: int
    sigma: float
    bias: float
    picks: List[float]  # hmotnosti dílků, každý tolikrát, kolik je ho v sáčku


def product_model(product: Product, index: int) -> _ProductModel:
    target = product.target_weight_g()
    element_var = sum(c.quantity * (ELEMENT_CV * float(c.element.weight_g)) ** 2 for c in product.components)
    sigma = math.sqrt(SCALE_NOISE_G ** 2 + FILM_NOISE_G ** 2 + element_var)
    # skutečné dílky váží nepatrně jinak než katalogová hodnota (každý výrobek trochu jinak)
    bias = ((index * 37) % 9 - 4) * 0.003
    picks = [float(c.element.weight_g) for c in product.components for _ in range(c.quantity)]
    return _ProductModel(
        target=float(target),
        target_c=int(target * 100),
        tol_c=int(product.tolerance_g() * 100),
        sigma=sigma,
        bias=bias,
        picks=picks,
    )


class WeighingGenerator:
    def __init__(
        self,
        master: MasterData,
        calendar: ShiftCalendar,
        scenarios: Sequence[Scenario],
        rng: random.Random,
    ) -> None:
        self.master = master
        self.calendar = calendar
        self.scenarios = list(scenarios)
        self.rng = rng
        self._models = {p.product_no: product_model(p, i) for i, p in enumerate(master.products)}

    def generate(self, runs: Sequence[ProductionRun], ids: RowIds) -> Iterator[WeighingRow]:
        tz = self.calendar.tz
        rnd = self.rng.random
        gauss = self.rng.gauss
        choice = self.rng.choice
        scenarios = self.scenarios

        for run in runs:
            scale = self.master.scale_for_line(run.line.code)
            model = self._models[run.product.product_no]
            scale_id = ids.scales[scale.code]
            run_id = ids.runs[run.run_no]
            per_minute = run.line.nominal_speed_ppm
            interval = 60.0 / per_minute
            t0 = run.starts_at.timestamp()
            t_end = run.ends_at.timestamp()

            minute = 0
            while True:
                m_start = t0 + minute * 60.0
                if m_start >= t_end:
                    break
                si = self.calendar.shift_index_at_epoch(m_start)
                if si < 0:
                    raise ValueError(f"Čas {datetime.fromtimestamp(m_start, tz)} není v žádné směně")
                shift = self.calendar.shifts[si]
                ctx = WeighingContext(
                    line_code=run.line.code,
                    scale_code=scale.code,
                    crew_code=shift.crew.code,
                    shift_type_code=shift.shift_type.code,
                    ts=datetime.fromtimestamp(m_start, tz),
                    minutes_since_run_start=float(minute),
                )
                # parametry na tuto minutu: běžný stav + úpravy ze scénářů
                p_missing, p_extra = BASE_MISSING_RATE, BASE_EXTRA_RATE
                if minute < BASE_RAMPUP_MINUTES:
                    p_missing = max(p_missing, BASE_RAMPUP_REJECT * 0.7)
                    p_extra = max(p_extra, BASE_RAMPUP_REJECT * 0.3)
                offset = 0.0
                for s in scenarios:
                    offset += s.scale_offset_g(ctx)
                    p_missing = s.missing_rate(ctx, p_missing)
                    p_extra = s.extra_rate(ctx, p_extra)
                p_defect = p_missing + p_extra
                mean = model.target + model.bias + offset
                shift_id = ids.shifts[si]

                for k in range(per_minute):
                    ts = m_start + k * interval + rnd() * JITTER_S
                    if ts >= t_end:
                        break
                    w = gauss(mean, model.sigma)
                    u = rnd()
                    if u < p_missing:
                        w -= choice(model.picks) * (1.0 + gauss(0.0, ELEMENT_CV))
                    elif u < p_defect:
                        w += choice(model.picks) * (1.0 + gauss(0.0, ELEMENT_CV))
                    wc = int(round(w * 100.0))
                    dev = wc - model.target_c
                    if dev < -model.tol_c:
                        result = "UNDER"
                    elif dev > model.tol_c:
                        result = "OVER"
                    else:
                        result = "OK"
                    yield WeighingRow(
                        scale_id,
                        datetime.fromtimestamp(ts, tz),
                        run_id,
                        shift_id,
                        Decimal(wc).scaleb(-2),
                        result,
                    )
                minute += 1
