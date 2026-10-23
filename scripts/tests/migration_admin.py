"""Применение SQL миграций от суперпользователя (ADMIN_DSN) без psql argv."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
import pytest


def admin_dsn_for_test_db(test_dsn: str) -> str:
    admin = os.environ.get("ADMIN_DSN", "").strip()
    if not admin:
        raise RuntimeError("ADMIN_DSN не задан")
    base = admin.rsplit("/", 1)[0]
    dbname = urlparse(test_dsn).path.lstrip("/") or "memory_test"
    return f"{base}/{dbname}"


def apply_sql_file(dsn: str, path: Path) -> None:
    try:
        conn = psycopg2.connect(dsn)
    except psycopg2.OperationalError as e:
        pytest.skip(f"ADMIN_DSN недоступен: {e}")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(path.read_text(encoding="utf-8"))
    cur.close()
    conn.close()
