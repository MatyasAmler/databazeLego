"""Příkazová řádka: python -m hlidac <příkaz>."""
from __future__ import annotations

import argparse
import sys
import time
from typing import List, Optional

from hlidac import __version__
from hlidac.analysis import AnalysisService
from hlidac.config import Settings
from hlidac.db import Database, Migrator
from hlidac.report.builder import ReportBuilder
from hlidac.simulation import Simulation


def _db(settings: Settings) -> Database:
    return Database(settings.database_url, settings.timezone)


def cmd_migrate(settings: Settings) -> None:
    applied = Migrator(_db(settings), settings.migrations_dir).migrate()
    print("Migrace:", ", ".join(applied) if applied else "nic nového")


def cmd_reset(settings: Settings) -> None:
    applied = Migrator(_db(settings), settings.migrations_dir).reset()
    print("Schéma založeno znovu, migrace:", ", ".join(applied))


def cmd_simulate(settings: Settings) -> None:
    s = Simulation(settings, _db(settings)).run()
    weighings = f"{s.weighings:,}".replace(",", " ")
    print(
        f"Simulace {settings.sim_start} + {settings.sim_days} dní: {s.shifts} směn, {s.runs} zakázek, "
        f"{weighings} vážení, {s.calibrations} kalibrace ({s.seconds:.1f} s)"
    )
    for name in s.scenarios:
        print("  scénář:", name)


def cmd_analyze(settings: Settings) -> None:
    result = AnalysisService(_db(settings)).run()
    print(f"Analýza: {len(result.alerts)} upozornění ({result.seconds:.1f} s)")
    for a in result.alerts:
        print(f"  [{a.severity.value}] {a.alert_type.value} {a.line_code}: {a.message}")


def cmd_report(settings: Settings) -> None:
    path = ReportBuilder(_db(settings), settings).build(settings.report_path)
    print("Report:", path)


def cmd_all(settings: Settings) -> None:
    started = time.perf_counter()
    cmd_reset(settings)
    cmd_simulate(settings)
    cmd_analyze(settings)
    cmd_report(settings)
    print(f"Hotovo za {time.perf_counter() - started:.1f} s")


COMMANDS = {
    "migrate": (cmd_migrate, "provede nové SQL migrace"),
    "reset": (cmd_reset, "smaže schéma a provede všechny migrace znovu"),
    "simulate": (cmd_simulate, "nasimuluje provoz a uloží ho do databáze"),
    "analyze": (cmd_analyze, "spustí detektory a uloží upozornění"),
    "report": (cmd_report, "vytvoří HTML report"),
    "all": (cmd_all, "vše od začátku: reset, simulace, analýza, report"),
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="hlidac", description="Hlídač vážení - sledování kontrolních vah")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in COMMANDS.items():
        sub.add_parser(name, help=help_text)
    args = parser.parse_args(argv)
    COMMANDS[args.command][0](Settings.from_env())
    return 0


if __name__ == "__main__":
    sys.exit(main())
