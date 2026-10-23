"""Подготовка тестовой БД (schema + migrations)."""
import os
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[2]


def apply_schema(dsn: str, *, migrations_only: bool = False):
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    if not migrations_only:
        schema = ROOT / "references" / "schema.sql"
        cur.execute(open(schema, encoding="utf-8").read())
    mig_dir = ROOT / "references" / "migrations"
    for path in sorted(mig_dir.glob("*.sql")):
        if path.name.endswith("_down.sql"):
            continue
        cur.execute(open(path, encoding="utf-8").read())
    cur.close()
    conn.close()


def apply_migrations(dsn: str):
    apply_schema(dsn, migrations_only=True)


def get_test_dsn():
    return os.environ.get("TEST_PG_DSN", "")
