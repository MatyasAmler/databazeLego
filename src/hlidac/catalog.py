"""Kmenová data pro simulaci: linky, váhy, dílky, výrobky, party a typy směn.

Hodnoty jsou smyšlené, ale realistické (hmotnosti malých plastových dílků v gramech).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from typing import Dict, List, Tuple

from hlidac.domain import Crew, Element, Line, Product, ProductComponent, Scale, ShiftType

D = Decimal

ELEMENTS: List[Tuple[str, str, str]] = [
    ("D-1001", "Kostka 2x4", "2.320"),
    ("D-1002", "Kostka 2x2", "1.160"),
    ("D-1003", "Kostka 1x2", "0.820"),
    ("D-1004", "Kostka 1x1", "0.450"),
    ("D-1005", "Kostka 1x4", "1.360"),
    ("D-1006", "Kostka 1x6", "1.920"),
    ("D-1007", "Destička 2x4", "1.050"),
    ("D-1008", "Destička 2x2", "0.550"),
    ("D-1009", "Destička 1x2", "0.360"),
    ("D-1010", "Destička 1x4", "0.720"),
    ("D-1011", "Destička 2x6", "1.620"),
    ("D-1012", "Dlaždice 1x2", "0.420"),
    ("D-1013", "Střešní taška 2x1", "0.710"),
    ("D-1014", "Okno 1x2x2", "1.100"),
    ("D-1015", "Kolo malé", "0.380"),
    ("D-1016", "Pneumatika", "0.660"),
    ("D-1017", "Kulatá kostka 1x1", "0.450"),
    ("D-1018", "Oblouk 1x4", "1.240"),
]

# číslo výrobku, název, fólie (g), složení [(číslo dílku, počet)]
PRODUCTS: List[Tuple[str, str, str, List[Tuple[str, int]]]] = [
    ("S-2001", "Sáček 1 - základní kostky", "1.350",
     [("D-1001", 6), ("D-1002", 8), ("D-1003", 10), ("D-1004", 12), ("D-1005", 4)]),
    ("S-2002", "Sáček 2 - destičky", "1.200",
     [("D-1007", 6), ("D-1008", 10), ("D-1009", 12), ("D-1010", 6), ("D-1011", 2)]),
    ("S-2003", "Sáček 3 - podvozek", "1.280",
     [("D-1015", 8), ("D-1016", 8), ("D-1007", 4), ("D-1003", 6), ("D-1012", 6)]),
    ("S-2004", "Sáček 4 - okna a střecha", "1.420",
     [("D-1014", 6), ("D-1013", 12), ("D-1002", 6), ("D-1018", 4)]),
    ("S-2005", "Sáček 5 - dlouhé kostky", "1.550",
     [("D-1006", 6), ("D-1005", 8), ("D-1010", 8), ("D-1011", 3)]),
    ("S-2006", "Sáček 6 - malý mix", "1.200",
     [("D-1004", 10), ("D-1009", 10), ("D-1012", 10), ("D-1017", 10)]),
    ("S-2007", "Sáček 7 - velký mix", "1.500",
     [("D-1001", 4), ("D-1002", 4), ("D-1003", 6), ("D-1007", 4), ("D-1008", 6),
      ("D-1013", 4), ("D-1014", 2), ("D-1016", 4), ("D-1018", 2)]),
    ("S-2008", "Sáček 8 - oblouky a dlaždice", "1.300",
     [("D-1018", 6), ("D-1012", 12), ("D-1008", 8), ("D-1017", 6)]),
]

# které výrobky se balí na které lince
LINE_PRODUCTS: Dict[str, List[str]] = {
    "PP-01": ["S-2001", "S-2007", "S-2004"],
    "PP-02": ["S-2002", "S-2006", "S-2008"],
    "PP-03": ["S-2003", "S-2001", "S-2005"],
    "PP-04": ["S-2004", "S-2007", "S-2002"],
    "PP-05": ["S-2005", "S-2002", "S-2006"],
    "PP-06": ["S-2006", "S-2008", "S-2003"],
    "PP-07": ["S-2007", "S-2003", "S-2008"],
    "PP-08": ["S-2008", "S-2005", "S-2001"],
}


@dataclass(frozen=True)
class MasterData:
    lines: Tuple[Line, ...]
    scales: Tuple[Scale, ...]
    elements: Tuple[Element, ...]
    products: Tuple[Product, ...]
    crews: Tuple[Crew, ...]
    shift_types: Tuple[ShiftType, ...]
    line_products: Dict[str, Tuple[str, ...]]

    def products_for_line(self, code: str) -> List[Product]:
        by_no = {p.product_no: p for p in self.products}
        return [by_no[no] for no in self.line_products[code]]

    def scale_for_line(self, code: str) -> Scale:
        return next(s for s in self.scales if s.line_code == code)

    def product(self, product_no: str) -> Product:
        return next(p for p in self.products if p.product_no == product_no)


def build_master_data() -> MasterData:
    elements = {no: Element(no, name, D(w)) for no, name, w in ELEMENTS}
    products = tuple(
        Product(no, name, D(film), tuple(ProductComponent(elements[e], q) for e, q in comp))
        for no, name, film, comp in PRODUCTS
    )
    lines = tuple(Line(f"PP-{i:02d}", f"Balicí linka {i}", 40) for i in range(1, 9))
    scales = tuple(Scale(f"CW-1{i:02d}", f"SN-24-{100 + i:04d}", D("0.010"), f"PP-{i:02d}") for i in range(1, 9))
    crews = tuple(Crew(code, offset, f"Parta {code}") for code, offset in (("A", 0), ("B", 2), ("C", 4), ("D", 6)))
    shift_types = (
        ShiftType("D", "Denní", time(6, 0), 12),
        ShiftType("N", "Noční", time(18, 0), 12),
    )
    return MasterData(
        lines=lines,
        scales=scales,
        elements=tuple(elements.values()),
        products=products,
        crews=crews,
        shift_types=shift_types,
        line_products={k: tuple(v) for k, v in LINE_PRODUCTS.items()},
    )
