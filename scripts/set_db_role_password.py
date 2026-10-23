#!/usr/bin/env python3
"""Создание/смена пароля роли БД без передачи пароля в argv psql."""
from __future__ import annotations

import os
import sys

import psycopg2
from psycopg2 import sql


def _admin_dsn(dbname: str = "postgres") -> str:
    admin = os.environ.get("ADMIN_DSN", "").strip()
    if admin:
        base = admin.rsplit("/", 1)[0]
        return f"{base}/{dbname}"
    return f"postgresql:///{dbname}"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: set_db_role_password.py <role_name>", file=sys.stderr)
        return 2
    role = sys.argv[1]
    password = os.environ.get("MEMORY_DB_PASSWORD", "")
    if not password:
        print("MEMORY_DB_PASSWORD не задан", file=sys.stderr)
        return 2
    dsn = _admin_dsn("postgres")
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    exists = cur.fetchone() is not None
    if exists:
        cur.execute(
            sql.SQL("ALTER ROLE {} LOGIN PASSWORD %s").format(sql.Identifier(role)),
            (password,),
        )
    else:
        cur.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s").format(sql.Identifier(role)),
            (password,),
        )
    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
