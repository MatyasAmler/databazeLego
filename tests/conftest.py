"""Společné fixture pro testy."""
from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from hlidac.config import Settings
from hlidac.db import Database, Migrator

TEST_DB = "hlidac_test"


def _with_db(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path="/" + name))


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings.from_env()


@pytest.fixture(scope="session")
def test_settings(settings: Settings) -> Settings:
    """Nastavení s vlastní testovací databází (ostatní data zůstanou netknutá)."""
    try:
        with psycopg.connect(_with_db(settings.database_url, "postgres"), autocommit=True, connect_timeout=3) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
            conn.execute(f"CREATE DATABASE {TEST_DB}")
    except psycopg.OperationalError as exc:
        pytest.skip(f"Databáze neběží (docker compose up -d): {exc}")
    return settings.with_overrides(database_url=_with_db(settings.database_url, TEST_DB))


@pytest.fixture()
def test_db(test_settings: Settings) -> Database:
    """Čisté schéma pro každý test."""
    db = Database(test_settings.database_url, test_settings.timezone)
    Migrator(db, test_settings.migrations_dir).reset()
    return db


def full_run_enabled() -> bool:
    return os.environ.get("HLIDAC_FULL") == "1"
