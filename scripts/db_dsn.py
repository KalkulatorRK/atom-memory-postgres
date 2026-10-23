"""Сборка DSN PostgreSQL без поломки query-string (?sslmode=...)."""
from __future__ import annotations

import os
import sys
from urllib.parse import urlparse, urlunparse


def admin_dsn_for_database(admin_dsn: str, dbname: str) -> str:
    u = urlparse(admin_dsn.strip())
    path = "/" + dbname.lstrip("/")
    return urlunparse((u.scheme, u.netloc, path, u.params, u.query, u.fragment))


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] != "admin-url":
        print("usage: db_dsn.py admin-url", file=sys.stderr)
        return 2
    admin = os.environ.get("ADMIN_DSN", "").strip()
    dbname = os.environ.get("DB_NAME", "postgres")
    if not admin:
        print("ADMIN_DSN не задан", file=sys.stderr)
        return 2
    print(admin_dsn_for_database(admin, dbname))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
