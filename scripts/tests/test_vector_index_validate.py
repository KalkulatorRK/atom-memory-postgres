import os
import subprocess

import psycopg2
import pytest

from vector_index import hnsw_index_name
from vector_index_validate import normalize_mem


def test_normalize_mem_ok():
    assert normalize_mem("1GB") == "1GB"
    assert normalize_mem("512kB") == "512kB"
    assert normalize_mem("128MB") == "128MB"


@pytest.mark.parametrize("bad", ["1gb", "5", "512KB", "64KB", "0MB", "", "99999999TB"])
def test_normalize_mem_rejects(bad):
    with pytest.raises(ValueError):
        normalize_mem(bad)


@pytest.fixture
def db_ready():
    from _db_guard import require
    from db_fixtures import get_test_dsn

    dsn = get_test_dsn()
    require(dsn, os.environ.get("PG_DSN", ""))
    return dsn


def _index_exists(conn, name: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (name,))
    row = cur.fetchone()
    cur.close()
    return row is not None


def _run_vector_admin(db: str, mem: str, *, drop: bool = False) -> subprocess.CompletedProcess:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "vector_index_admin.sh")
    cmd = ["bash", script, "--model", "fake:hash-v1", "--dims", "768", "--mem", mem]
    if drop:
        cmd.append("--drop")
    env = {**os.environ, "PGDATABASE": db}
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


@pytest.mark.db
@pytest.mark.parametrize("bad_mem", ["512KB", "64KB", "99999999TB"])
def test_bad_mem_keeps_index(db_ready, bad_mem):
    from urllib.parse import urlparse

    idx = hnsw_index_name("fake:hash-v1", 768)
    dbname = urlparse(db_ready).path.lstrip("/")
    conn = psycopg2.connect(db_ready)
    if not _index_exists(conn, idx):
        pytest.skip("HNSW index not present in test DB")
    conn.close()

    proc = _run_vector_admin(dbname, bad_mem, drop=True)
    assert proc.returncode != 0

    conn = psycopg2.connect(db_ready)
    assert _index_exists(conn, idx), f"index {idx} must survive bad --mem {bad_mem!r}"
    conn.close()


def test_vector_admin_validates_before_drop():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "vector_index_admin.sh")
    r = subprocess.run(
        ["bash", script, "--model", "fake:hash-v1", "--dims", "768", "--drop", "--mem", "512KB"],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "KB" in r.stderr or "kB" in r.stderr
