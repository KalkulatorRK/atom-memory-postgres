"""Применение SQL миграций от суперпользователя (ADMIN_DSN) без psql argv."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg2

from db_dsn import admin_dsn_for_database


def admin_dsn_for_test_db(test_dsn: str) -> str:
    admin = os.environ.get("ADMIN_DSN", "").strip()
    if not admin:
        raise RuntimeError("ADMIN_DSN не задан")
    dbname = urlparse(test_dsn).path.lstrip("/") or "memory_test"
    return admin_dsn_for_database(admin, dbname)


def apply_sql_file(dsn: str, path: Path) -> None:
    try:
        conn = psycopg2.connect(dsn)
    except psycopg2.OperationalError as e:
        if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true":
            raise AssertionError(f"ADMIN_DSN недоступен в CI: {e}") from e
        import pytest

        pytest.skip(f"ADMIN_DSN недоступен: {e}")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(path.read_text(encoding="utf-8"))
    cur.close()
    conn.close()
