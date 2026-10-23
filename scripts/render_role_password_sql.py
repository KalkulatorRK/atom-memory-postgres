#!/usr/bin/env python3
"""SQL для CREATE/ALTER ROLE: format()+\\gexec, SCRAM-хэш без plaintext на сервере."""
from __future__ import annotations

import os
import sys

from pg_scram import scram_sha256_password


def _pg_sql_literal(value: str) -> str:
    if "\x00" in value:
        raise ValueError("NUL byte in SQL literal value")
    return "'" + value.replace("'", "''") + "'"


def _validate_role(role: str) -> None:
    if not role:
        raise ValueError("empty role name")
    if "\x00" in role:
        raise ValueError("NUL byte in role name")
    if role.lower().startswith("pg_"):
        raise ValueError(f"reserved PostgreSQL role name: {role}")


def render_role_password_sql(role: str, password: str) -> str:
    _validate_role(role)
    if "\x00" in password:
        raise ValueError("NUL byte in password")
    r = _pg_sql_literal(role)
    scram = scram_sha256_password(password)
    p = _pg_sql_literal(scram)
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
