"""Регрессии polish v1.9.1."""
import json
import os
import subprocess
import sys
from io import StringIO
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.db


def test_mcp_hybrid_warnings_still_json_array():
    from memory_mcp_server import format_memory_search_response

    hits = [{"id": 1, "content": "x"}]
    text = format_memory_search_response(
        hits,
        ["векторный поиск выключен: не задан EMBED_API_KEY"],
        include_warnings=False,
    )
    data = json.loads(text)
    assert isinstance(data, list)


def test_mcp_include_warnings_opt_in():
    from memory_mcp_server import format_memory_search_response

    text = format_memory_search_response([], ["w"], include_warnings=True)
    assert json.loads(text)["warnings"] == ["w"]


def test_calibrate_min_sim_runs_offline():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, "EMBED_PROVIDER": "fake"}
    r = subprocess.run(
        [sys.executable, os.path.join(root, "calibrate_min_sim.py")],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "EMBED_MIN_SIM" in r.stdout


def test_setup_skips_schema_when_atoms_exist():
    text = open(
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "setup_memory_db.sh"),
        encoding="utf-8",
    ).read()
    assert "to_regclass('public.atoms')" in text
    assert "пропуск schema.sql" in text


def test_memory_query_fts_json():
    from memory_query import main

    if not os.environ.get("PG_DSN"):
        pytest.skip("PG_DSN")
    buf = StringIO()
    with patch.object(sys, "argv", ["memory_query.py", "test", "--mode", "fts", "--json", "--limit", "1"]):
        with patch("sys.stdout", buf):
            main()
    out = buf.getvalue()
    payload = json.loads(out)
    assert "results" in payload
    assert payload["mode_used"] == "fts"


@pytest.fixture
def db_ready():
    from _db_guard import require
    from db_fixtures import get_test_dsn

    dsn = get_test_dsn()
    require(dsn, os.environ.get("PG_DSN", ""))
    return dsn


def test_migration_down_idempotent(db_ready):
    if not os.environ.get("ADMIN_DSN"):
        pytest.skip("ADMIN_DSN")
    from pathlib import Path

    from migration_admin import admin_dsn_for_test_db, apply_sql_file

    root = Path(__file__).resolve().parents[2]
    admin_db = admin_dsn_for_test_db(db_ready)
    down = root / "references/migrations/0004_vector_search_down.sql"
    up = root / "references/migrations/0004_vector_search.sql"
    try:
        apply_sql_file(admin_db, down)
        apply_sql_file(admin_db, down)
    finally:
        apply_sql_file(admin_db, up)
