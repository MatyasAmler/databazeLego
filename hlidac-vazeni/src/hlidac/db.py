"""Připojení k PostgreSQL a spouštění SQL migrací."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List

import psycopg


class Database:
    """Továrna na připojení. Každé připojení má nastavené časové pásmo provozu."""

    def __init__(self, url: str, timezone: str = "Europe/Prague") -> None:
        self.url = url
        self.timezone = timezone

    @contextmanager
    def connect(self, autocommit: bool = False) -> Iterator[psycopg.Connection]:
        """Připojení jako transakce: při úspěchu commit, při výjimce rollback."""
        with psycopg.connect(self.url, autocommit=autocommit, options=f"-c timezone={self.timezone}") as conn:
            yield conn


class Migrator:
    """Spouští soubory db/migrations/NNN_*.sql v pořadí a eviduje je v tabulce schema_migrations."""

    def __init__(self, db: Database, directory: Path) -> None:
        self.db = db
        self.directory = directory

    def migrate(self) -> List[str]:
        applied: List[str] = []
        with self.db.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            for path in sorted(self.directory.glob("*.sql")):
                if path.name in done:
                    continue
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
                applied.append(path.name)
        return applied

    def reset(self) -> List[str]:
        """Smaže celé schéma public a provede všechny migrace znovu."""
        with self.db.connect(autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
            conn.execute("CREATE SCHEMA public")
        return self.migrate()
