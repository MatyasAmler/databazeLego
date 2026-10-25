"""Nastavení aplikace z proměnných prostředí (a ze souboru .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Načte jednoduchý soubor KEY=VALUE. Už nastavené proměnné nepřepisuje."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    database_url: str = "postgresql://hlidac:hlidac@localhost:5433/hlidac"
    timezone: str = "Europe/Prague"
    sim_start: date = date(2026, 10, 5)
    sim_days: int = 16
    seed: int = 42
    rampup_minutes: int = 20  # musí odpovídat intervalu v db/migrations/002_analytics.sql
    migrations_dir: Path = ROOT / "db" / "migrations"
    report_path: Path = ROOT / "out" / "report.html"

    @classmethod
    def from_env(cls, env_file: Optional[Path] = None) -> "Settings":
        _load_dotenv(env_file or ROOT / ".env")
        env = os.environ
        defaults = cls()
        return cls(
            database_url=env.get("DATABASE_URL", defaults.database_url),
            timezone=env.get("HLIDAC_TIMEZONE", defaults.timezone),
            sim_start=date.fromisoformat(env.get("HLIDAC_SIM_START", defaults.sim_start.isoformat())),
            sim_days=int(env.get("HLIDAC_SIM_DAYS", defaults.sim_days)),
            seed=int(env.get("HLIDAC_SEED", defaults.seed)),
            report_path=Path(env.get("HLIDAC_REPORT_PATH", defaults.report_path)),
        )

    def with_overrides(self, **changes) -> "Settings":
        return replace(self, **changes)
