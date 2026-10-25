"""HTML report pro mistra, kvalitu a vedení výroby."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from typing import List

from psycopg.rows import namedtuple_row

from hlidac.analysis.base import count, pct, pp, when
from hlidac.config import Settings
from hlidac.db import Database
from hlidac.report.charts import dot_chart, heat_color, spc_chart
from hlidac.repository import AlertRepository

TYPE_NAME = {
    "SCALE_DRIFT": "Posun kalibrace váhy",
    "CREW_QUALITY": "Problém party",
    "CHANGEOVER_RAMPUP": "Rozběh po přestavbě",
}
SEVERITY = {"CRITICAL": ("kritické", "#c62828"), "WARNING": ("varování", "#b45309"), "INFO": ("info", "#1d4ed8")}

CSS = """
body{font-family:Arial,Helvetica,sans-serif;color:#222;margin:0;background:#fff}
main{max-width:980px;margin:0 auto;padding:24px 20px 40px}
h1{font-size:28px;margin:0 0 4px}
h2{font-size:20px;margin:32px 0 10px;padding-bottom:4px;border-bottom:1px solid #ccc}
.sub{color:#666;margin:0 0 16px}
table{border-collapse:collapse;width:100%;font-size:14px;margin:6px 0}
th,td{border:1px solid #ccc;padding:6px 8px;text-align:right;vertical-align:top}
th:first-child,td:first-child{text-align:left}
th{background:#f0f0f0}
table.alerts th,table.alerts td{text-align:left}
table.alerts td:nth-child(2){width:200px}
table.alerts td.sev{font-weight:bold;white-space:nowrap}
table.summary{width:auto}
table.summary td{text-align:left}
.note{color:#666;font-size:13px;margin:6px 0 0}
footer{color:#888;font-size:12px;margin-top:30px}
"""


class ReportBuilder:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def build(self, path: Path) -> Path:
        with self.db.connect() as conn:
            with conn.cursor(row_factory=namedtuple_row) as cur:
                totals = cur.execute(
                    "SELECT sum(n) AS n, sum(n_under) AS under, sum(n_over) AS over, "
                    "min(hour) AS first, max(hour) AS last FROM mv_hourly_stats"
                ).fetchone()
                lines = cur.execute(
                    "SELECT l.code, count(DISTINCT h.run_id) AS runs, sum(h.n) AS n, sum(h.n_under) AS under, "
                    "sum(h.n_over) AS over FROM mv_hourly_stats h JOIN line l USING (line_id) GROUP BY l.code ORDER BY l.code"
                ).fetchall()
                crews = cur.execute(
                    "SELECT line_code, shift_type_code, crew_code, under_rate FROM v_quality_by_crew"
                ).fetchall()
                rampup = cur.execute(
                    "SELECT line_code, rampup_reject_rate, steady_reject_rate FROM v_rampup_by_line ORDER BY line_code"
                ).fetchall()
                hourly = cur.execute(
                    "SELECT scale_code, hour, reject_rate, mean_dev_ok, n_ok_steady FROM v_scale_hourly ORDER BY scale_code, hour"
                ).fetchall()
                calibrations = cur.execute(
                    "SELECT s.code AS scale_code, c.calibrated_at FROM calibration c JOIN scale s USING (scale_id)"
                ).fetchall()
            alerts = AlertRepository(conn).list()

        html = self._render(totals, lines, crews, rampup, hourly, calibrations, alerts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        return path

    # ------------------------------------------------------------------ části reportu

    def _render(self, totals, lines, crews, rampup, hourly, calibrations, alerts) -> str:
        n = int(totals.n or 0)
        under, over = int(totals.under or 0), int(totals.over or 0)
        crit = sum(1 for a in alerts if a["severity"] == "CRITICAL")
        period = f"{when(totals.first)} - {when(totals.last + timedelta(hours=1))}" if totals.first else "-"
        order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
        alerts = sorted(alerts, key=lambda a: (order.get(a["severity"], 9), a["valid_from"]))
        parts = [
            "<!doctype html><html lang='cs'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>Hlídač vážení - report</title><style>{CSS}</style></head><body><main>",
            "<h1>Hlídač vážení - report</h1>",
            f"<p class='sub'>Období {period}, {len(lines)} linek, vytvořeno {datetime.now():%d. %m. %Y %H:%M}</p>",
            "<table class='summary'>",
            f"<tr><td>Zvážených sáčků</td><td><b>{count(n)}</b></td></tr>",
            f"<tr><td>Podváha</td><td>{pct(under / n if n else 0, 2)} ({count(under)} sáčků)</td></tr>",
            f"<tr><td>Nadváha</td><td>{pct(over / n if n else 0, 2)} ({count(over)} sáčků)</td></tr>",
            f"<tr><td>Upozornění</td><td>{len(alerts)}, z toho {crit} kritická</td></tr>",
            "</table>",
            "<h2>Upozornění</h2>",
            self._alerts_table(alerts),
        ]
        parts += self._drift_section(alerts, hourly, calibrations)
        parts += self._crew_section(crews)
        parts += self._rampup_section(rampup, alerts)
        parts += self._lines_section(lines, alerts)
        parts.append("<footer>Simulovaná data, vytvořeno příkazem python -m hlidac report.</footer></main></body></html>")
        return "".join(parts)

    @staticmethod
    def _alerts_table(alerts) -> str:
        if not alerts:
            return "<p>Žádná upozornění.</p>"
        rows = []
        for a in alerts:
            label, color = SEVERITY.get(a["severity"], ("", "#666"))
            target = ", ".join(x for x in (a["line_code"], a["scale_code"] and f"váha {a['scale_code']}",
                                           a["crew_code"] and f"parta {a['crew_code']}") if x)
            span = when(a["valid_from"]) + (f" - {when(a['valid_to'])}" if a["valid_to"] else "")
            rows.append(
                f"<tr><td class='sev' style='color:{color}'>{label}</td>"
                f"<td><b>{TYPE_NAME.get(a['alert_type'], a['alert_type'])}</b><br>{escape(target)}<br>{escape(span)}</td>"
                f"<td>{escape(a['message'])}</td></tr>"
            )
        return ("<table class='alerts'><tr><th>Závažnost</th><th>Co a kde</th><th>Popis</th></tr>"
                + "".join(rows) + "</table>")

    def _drift_section(self, alerts, hourly, calibrations) -> List[str]:
        out = []
        for a in (a for a in alerts if a["alert_type"] == "SCALE_DRIFT"):
            d = a["details"] if isinstance(a["details"], dict) else json.loads(a["details"])
            rows = [r for r in hourly if r.scale_code == a["scale_code"]]
            points = [(r.hour, float(r.mean_dev_ok) if r.mean_dev_ok is not None and r.n_ok_steady >= 50 else None)
                      for r in rows]
            reject = [(r.hour, float(r.reject_rate)) for r in rows]
            markers = [(datetime.fromisoformat(d["detected_at"]), "upozornění", "#2563eb")]
            if d.get("first_hour_reject_over_limit"):
                markers.append((datetime.fromisoformat(d["first_hour_reject_over_limit"]), "výmět > 1 %", "#dc2626"))
            for c in calibrations:
                if c.scale_code == a["scale_code"]:
                    markers.append((c.calibrated_at, "kalibrace", "#16a34a"))
            window = (a["valid_from"], a["valid_to"])
            detail = (a["valid_from"] - timedelta(hours=18), a["valid_to"] + timedelta(hours=10))
            out += [
                f"<h2>Regulační diagram váhy {escape(a['scale_code'])}</h2>",
                "<p class='note'>Celé období:</p>",
                spc_chart(points, reject, d["baseline_mean_g"], d["ucl_g"], d["lcl_g"], [], window),
                "<p class='note'>Detail kolem upozornění:</p>",
                spc_chart(points, reject, d["baseline_mean_g"], d["ucl_g"], d["lcl_g"], markers, window, detail),
                "<p class='note'>Modrá čára: hodinový průměr odchylky dobrých sáčků od cílové hmotnosti. "
                "Přerušovaně: regulační meze spočítané z prvních 4 dnů (průměr ± 3 σ). "
                "Červené pozadí: období mimo meze. Dole: hodinový výmět (červeně nad 1 %).</p>",
            ]
        return out

    def _crew_section(self, crews) -> List[str]:
        rate = {(r.line_code, r.shift_type_code, r.crew_code): float(r.under_rate or 0) for r in crews}
        line_codes = sorted({r.line_code for r in crews})
        values = list(rate.values()) or [0]
        low, high = min(values), max(values)
        head = "".join(f"<th>{st} {c}</th>" for st in ("den", "noc") for c in "ABCD")
        body = []
        for line in line_codes:
            cells = []
            for st in ("D", "N"):
                for c in "ABCD":
                    v = rate.get((line, st, c))
                    cells.append(f"<td style='background:{heat_color(v, low, high)}'>{pct(v, 2)}</td>"
                                 if v is not None else "<td>-</td>")
            body.append(f"<tr><td><b>{line}</b></td>{''.join(cells)}</tr>")
        return [
            "<h2>Sáčky s chybějícím dílkem podle part</h2>",
            f"<table><tr><th>Linka</th>{head}</tr>{''.join(body)}</table>",
            "<p class='note'>Podíl podváhy v ustáleném provozu (bez prvních 20 minut zakázek). "
            "Porovnávají se party na stejném typu směny, takže je vidět, jestli jde o problém party, nebo noci.</p>",
        ]

    def _rampup_section(self, rampup, alerts) -> List[str]:
        flagged = {a["line_code"] for a in alerts if a["alert_type"] == "CHANGEOVER_RAMPUP"}
        items = [(r.line_code, float(r.rampup_reject_rate) - float(r.steady_reject_rate), r.line_code in flagged)
                 for r in rampup]
        return [
            "<h2>Rozběh po přestavbě</h2>",
            dot_chart(items, lambda v: "+" + pp(v)),
            "<p class='note'>O kolik procentních bodů je výmět v prvních 20 minutách zakázky vyšší než "
            "v ustáleném provozu téže linky.</p>",
        ]

    @staticmethod
    def _lines_section(lines, alerts) -> List[str]:
        rows = "".join(
            f"<tr><td>{r.code}</td><td>{r.runs}</td><td>{count(int(r.n))}</td>"
            f"<td>{pct(float(r.under) / float(r.n), 2)}</td><td>{pct(float(r.over) / float(r.n), 2)}</td>"
            f"<td><b>{pct(float(r.under + r.over) / float(r.n), 2)}</b></td></tr>"
            for r in lines
        )
        return [
            "<h2>Linky za celé období</h2><table>"
            "<tr><th>Linka</th><th>Zakázek</th><th>Vážení</th><th>Podváha</th><th>Nadváha</th><th>Výmět</th></tr>",
            rows,
            "</table>",
        ]
