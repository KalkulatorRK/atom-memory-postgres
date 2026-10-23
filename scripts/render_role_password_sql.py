#!/usr/bin/env python3
"""SQL для CREATE/ALTER ROLE: format()+\\gexec, без dollar-quoting (безопасно для psql -f -)."""
from __future__ import annotations

import os
import sys


def _pg_sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_role_password_sql(role: str, password: str) -> str:
    r = _pg_sql_literal(role)
    p = _pg_sql_literal(password)
    return (
        "SELECT format(\n"
        "  CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
        f"{r})\n"
        "    THEN 'ALTER ROLE %I PASSWORD %L'\n"
        "    ELSE 'CREATE ROLE %I LOGIN PASSWORD %L'\n"
        "  END,\n"
        f"  {r}, {p}\n"
        ") \\gexec\n"
    )


def main() -> int:
    role = os.environ.get("DB_USER", "").strip()
    password = os.environ.get("MEMORY_DB_PASSWORD", "")
    if not role:
        print("DB_USER не задан", file=sys.stderr)
        return 2
    if not password:
        print("MEMORY_DB_PASSWORD не задан", file=sys.stderr)
        return 2
    sys.stdout.write(render_role_password_sql(role, password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
