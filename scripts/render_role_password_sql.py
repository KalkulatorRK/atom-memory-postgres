#!/usr/bin/env python3
"""SQL для CREATE/ALTER ROLE (stdlib). Пароль только из MEMORY_DB_PASSWORD, роль из DB_USER."""
from __future__ import annotations

import os
import sys


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def main() -> int:
    role = os.environ.get("DB_USER", "").strip()
    password = os.environ.get("MEMORY_DB_PASSWORD", "")
    if not role:
        print("DB_USER не задан", file=sys.stderr)
        return 2
    if not password:
        print("MEMORY_DB_PASSWORD не задан", file=sys.stderr)
        return 2
    r = _sql_literal(role)
    p = _sql_literal(password)
    print(
        f"""DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {r}) THEN
    EXECUTE format('ALTER ROLE %I PASSWORD %L', {r}, {p});
  ELSE
    EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', {r}, {p});
  END IF;
END $$;
"""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
