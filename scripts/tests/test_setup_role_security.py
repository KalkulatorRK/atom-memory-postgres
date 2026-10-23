"""Исполнение: пароль роли не должен ломать psql / shell."""
from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import psycopg2
import pytest

from render_role_password_sql import render_role_password_sql

pytestmark = pytest.mark.db


@pytest.fixture
def admin_db(db_ready):
    from migration_admin import admin_dsn_for_test_db

    if not os.environ.get("ADMIN_DSN"):
        pytest.skip("ADMIN_DSN")
    return admin_dsn_for_test_db(db_ready)


@pytest.fixture
def db_ready():
    from _db_guard import require
    from db_fixtures import get_test_dsn

    dsn = get_test_dsn()
    require(dsn, os.environ.get("PG_DSN", ""))
    return dsn


def _run_role_sql(admin_dsn: str, role: str, password: str) -> subprocess.CompletedProcess:
    sql = render_role_password_sql(role, password)
    assert "DO $$" not in sql
    assert "\\gexec" in sql
    proc = subprocess.run(
        ["psql", admin_dsn, "-v", "ON_ERROR_STOP=1", "-q", "-f", "-"],
        input=sql,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 and os.environ.get("GITHUB_ACTIONS") != "true":
        err = proc.stderr or ""
        if "password authentication failed" in err or "fe_sendauth" in err:
            pytest.skip(f"ADMIN_DSN недоступен: {err[:200]}")
    return proc


def _drop_role(admin_dsn: str, role: str) -> None:
    subprocess.run(
        ["psql", admin_dsn, "-v", "ON_ERROR_STOP=1", "-c", f'DROP ROLE IF EXISTS "{role}";'],
        check=False,
        capture_output=True,
    )


def _login_dsn(role: str, password: str, test_dsn: str) -> str:
    from urllib.parse import quote, urlparse

    u = urlparse(test_dsn)
    safe_pw = quote(password, safe="")
    return f"{u.scheme}://{quote(role, safe='')}:{safe_pw}@{u.hostname}:{u.port or 5432}{u.path}"


@pytest.mark.parametrize(
    "password",
    [
        "plain-secret",
        "quote'and\"mix",
        "semi;colon",
        "colon:var",
        "back`tick",
        r"back\slash",
        "gexec\\nword",
        "x$$ not-a-dollar-block",
        r"x \! echo pwn",
    ],
)
def test_role_password_special_chars(admin_db, db_ready, password):
    role = f"sec_{uuid.uuid4().hex[:12]}"
    marker = uuid.uuid4().hex
    pw = f"{password}__{marker}__"
    pwn = Path(f"/tmp/pwned_setup_{uuid.uuid4().hex}")
    if pwn.exists():
        pwn.unlink()
    try:
        proc = _run_role_sql(admin_db, role, pw)
        assert proc.returncode == 0, proc.stderr
        assert not pwn.exists(), "shell command from password must not run"
        assert marker not in proc.stderr
        assert pw not in proc.stderr
        conn = psycopg2.connect(_login_dsn(role, pw, db_ready))
        conn.close()
    finally:
        _drop_role(admin_db, role)
        if pwn.exists():
            pwn.unlink()


@pytest.mark.parametrize(
    "password",
    [
        "cafe\u0301",  # NFD é
        "\ufb01",  # fi ligature
        "\u00a0secret",  # NBSP
        "\uff11\uff12\uff13",  # full-width 123
    ],
)
def test_role_password_unicode_saslprep(admin_db, db_ready, password):
    role = f"uni_{uuid.uuid4().hex[:12]}"
    pw = f"{password}__{uuid.uuid4().hex[:6]}"
    try:
        proc = _run_role_sql(admin_db, role, pw)
        assert proc.returncode == 0, proc.stderr
        conn = psycopg2.connect(_login_dsn(role, pw, db_ready))
        conn.close()
    finally:
        _drop_role(admin_db, role)


def test_shell_injection_repro_password(admin_db, db_ready):
    """Регрессия B2: $$ + \\! не создаёт файл."""
    role = f"sec_{uuid.uuid4().hex[:12]}"
    pwn = Path("/tmp/pwned_b2_repro")
    if pwn.exists():
        pwn.unlink()
    password = "x$$ \\! touch /tmp/pwned_b2_repro #"
    try:
        proc = _run_role_sql(admin_db, role, password)
        assert proc.returncode == 0, proc.stderr
        assert not pwn.exists()
        assert "pwned_b2_repro" not in proc.stderr
        conn = psycopg2.connect(_login_dsn(role, password, db_ready))
        conn.close()
    finally:
        _drop_role(admin_db, role)
        if pwn.exists():
            pwn.unlink()
