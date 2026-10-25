"""Jednoduché SVG grafy pro HTML report (bez externích knihoven)."""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import List, Optional, Sequence, Tuple

INK = "#1f2933"
MUTED = "#6b7280"
GRID = "#e5e7eb"
BLUE = "#2563eb"
RED = "#dc2626"
AMBER = "#d97706"
GREEN = "#16a34a"
FONT = "Arial, Helvetica, sans-serif"


def _fmt(x: float, digits: int = 2) -> str:
    return f"{x:.{digits}f}".replace(".", ",").replace("-", "−")


def spc_chart(
    points: Sequence[Tuple[datetime, Optional[float]]],
    reject: Sequence[Tuple[datetime, float]],
    mu: float,
    ucl: float,
    lcl: float,
    markers: Sequence[Tuple[datetime, str, str]] = (),
    window: Optional[Tuple[datetime, datetime]] = None,
    t_range: Optional[Tuple[datetime, datetime]] = None,
    y_max: float = 0.35,
    y_min: float = -0.06,
    width: int = 980,
) -> str:
    """Regulační diagram: hodinový průměr odchylky (nahoře) a hodinový výmět (dole)."""
    if t_range:
        points = [p for p in points if t_range[0] <= p[0] < t_range[1]]
        reject = [r for r in reject if t_range[0] <= r[0] < t_range[1]]
    if not points:
        return ""
    tz = points[0][0].tzinfo
    left, right, top = 64, 16, 22 + 16 * len(markers)
    h1, gap, h2 = 230, 34, 90
    height = top + h1 + gap + h2 + 34
    t0 = min(t for t, _ in points).timestamp()
    t1 = max(t for t, _ in points).timestamp() + 3600
    pw = width - left - right
    hour_w = pw / ((t1 - t0) / 3600)

    def x(t: datetime) -> float:
        return left + (t.timestamp() - t0) / (t1 - t0) * pw

    def y(v: float) -> float:
        v = max(y_min, min(y_max, v))
        return top + (y_max - v) / (y_max - y_min) * h1

    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" font-family="{FONT}" font-size="12">']
    if window:
        wx0, wx1 = max(left, x(window[0])), min(width - right, x(window[1]))
        if wx1 > wx0:
            out.append(f'<rect x="{wx0:.1f}" y="{top}" width="{wx1 - wx0:.1f}" height="{h1 + gap + h2}" fill="#fee2e2" opacity="0.6"/>')
    # osa y a mřížka
    step = 0.05
    v = round(y_min / step) * step
    while v <= y_max + 1e-9:
        yy = y(v)
        out.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{width - right}" y2="{yy:.1f}" stroke="{GRID}"/>')
        out.append(f'<text x="{left - 8}" y="{yy + 4:.1f}" text-anchor="end" fill="{MUTED}">{_fmt(v)} g</text>')
        v += step
    # regulační meze
    for val, color in ((ucl, RED), (mu, MUTED), (lcl, RED)):
        out.append(f'<line x1="{left}" y1="{y(val):.1f}" x2="{width - right}" y2="{y(val):.1f}" '
                   f'stroke="{color}" stroke-dasharray="6 4" stroke-width="1.4"/>')
    out.append(f'<text x="{width - right - 4}" y="{y(ucl) - 5:.1f}" text-anchor="end" fill="{RED}">horní regulační mez</text>')
    # průběh (bod ve středu hodiny)
    path, pen = [], False
    for t, val in points:
        if val is None:
            pen = False
            continue
        path.append(("L" if pen else "M") + f"{x(t) + hour_w / 2:.1f},{y(val):.1f}")
        pen = True
    out.append(f'<path d="{" ".join(path)}" fill="none" stroke="{BLUE}" stroke-width="2"/>')
    # výmět dole
    yb = top + h1 + gap
    out.append(f'<text x="{left}" y="{yb - 8}" fill="{MUTED}">hodinový výmět (0-100 %)</text>')
    out.append(f'<line x1="{left}" y1="{yb + h2}" x2="{width - right}" y2="{yb + h2}" stroke="{GRID}"/>')
    bw = max(1.0, hour_w - 0.6)
    for t, r in reject:
        bh = max(0.0, min(1.0, r)) * h2
        color = RED if r > 0.01 else "#9ca3af"
        out.append(f'<rect x="{x(t):.1f}" y="{yb + h2 - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{color}"/>')
    # značky (popisky pod sebou, aby se nepřekrývaly)
    for i, (t, label, color) in enumerate(sorted(markers)):
        if not (t0 <= t.timestamp() <= t1):
            continue
        xx = x(t)
        ly = 14 + 16 * i
        anchor = "end" if xx > width - 220 else "start"
        dx = -4 if anchor == "end" else 4
        out.append(f'<line x1="{xx:.1f}" y1="{ly + 3}" x2="{xx:.1f}" y2="{yb + h2}" stroke="{color}" stroke-width="2"/>')
        out.append(f'<text x="{xx + dx:.1f}" y="{ly}" fill="{color}" font-weight="bold" text-anchor="{anchor}">'
                   f'{escape(label)} {t.day}. {t.month}. {t:%H:%M}</text>')
    # osa x: po dnech, u krátkého období po 6 hodinách
    tick_h = 24 if (t1 - t0) > 4 * 86400 else 6
    first = datetime.fromtimestamp(t0, tz).replace(minute=0, second=0, microsecond=0)
    tick = first.replace(hour=0)
    while tick.timestamp() < t1:
        if tick.timestamp() >= t0:
            xx = x(tick)
            label = f"{tick.day}. {tick.month}." if tick.hour == 0 else f"{tick:%H}:00"
            out.append(f'<line x1="{xx:.1f}" y1="{yb + h2}" x2="{xx:.1f}" y2="{yb + h2 + 5}" stroke="{MUTED}"/>')
            out.append(f'<text x="{xx:.1f}" y="{yb + h2 + 18}" text-anchor="middle" fill="{MUTED}">{label}</text>')
        tick = datetime.fromtimestamp(tick.timestamp() + tick_h * 3600, tz)
    out.append("</svg>")
    return "".join(out)


def dot_chart(items: Sequence[Tuple[str, float, bool]], unit_fmt, width: int = 960) -> str:
    """Bodový graf: u každé položky tenká čára od nuly a tečka na hodnotě. Zvýrazněné červeně."""
    row, left, right = 34, 70, 120
    height = len(items) * row + 30
    top_value = max(v for _, v, _ in items) * 1.08 or 1
    pw = width - left - right
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" font-family="{FONT}" font-size="13">']
    # mřížka po procentních bodech
    step = 0.01 if top_value <= 0.1 else 0.02
    v = 0.0
    while v <= top_value + 1e-9:
        xx = left + v / top_value * pw
        out.append(f'<line x1="{xx:.1f}" y1="6" x2="{xx:.1f}" y2="{height - 22}" stroke="{GRID}"/>')
        out.append(f'<text x="{xx:.1f}" y="{height - 6}" text-anchor="middle" fill="{MUTED}">{escape(unit_fmt(v))}</text>')
        v += step
    for i, (label, value, hl) in enumerate(items):
        yy = 6 + i * row + row / 2
        xx = left + max(0.0, value) / top_value * pw
        color = RED if hl else "#475569"
        out.append(f'<text x="0" y="{yy + 5:.1f}" fill="{RED if hl else INK}" font-weight="bold">{escape(label)}</text>')
        out.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{xx:.1f}" y2="{yy:.1f}" stroke="{color}" stroke-width="{3 if hl else 2}"/>')
        out.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="{8 if hl else 6}" fill="{color}"/>')
        out.append(f'<text x="{xx + 14:.1f}" y="{yy + 5:.1f}" fill="{color}" font-weight="{"bold" if hl else "normal"}">'
                   f'{escape(unit_fmt(value))}</text>')
    out.append("</svg>")
    return "".join(out)


def heat_color(value: float, low: float, high: float) -> str:
    """Bílá -> červená podle hodnoty mezi low a high."""
    t = 0.0 if high <= low else max(0.0, min(1.0, (value - low) / (high - low)))
    r, g, b = 255, int(255 - t * (255 - 70)), int(255 - t * (255 - 70))
    return f"rgb({r},{g},{b})"
