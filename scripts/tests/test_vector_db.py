import os

import psycopg2
import pytest

from _db_guard import require
from db_fixtures import get_test_dsn

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def db_ready():
    dsn = get_test_dsn()
    require(dsn, os.environ.get("PG_DSN", ""))
    return dsn


def test_migration_idempotent(db_ready):
    import subprocess

    from pathlib import Path

    mig = str(Path(__file__).resolve().parents[2] / "references" / "migrations" / "0004_vector_search.sql")
    for _ in range(2):
        subprocess.run(
            ["sudo", "-u", "postgres", "psql", "-d", "memory_test", "-v", "ON_ERROR_STOP=1", "-f", mig],
            check=True,
            capture_output=True,
        )
    conn = psycopg2.connect(db_ready)
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM pg_constraint WHERE conname='embeddings_atom_space_key'"
    )
    assert cur.fetchone()
    cur.execute("SELECT 1 FROM pg_indexes WHERE indexname='idx_emb_hnsw_fake_hash_v1_768'")
    assert cur.fetchone()
    conn.close()


def test_dims_check(db_ready):
    conn = psycopg2.connect(db_ready)
    cur = conn.cursor()
    cur.execute("SELECT id FROM atoms LIMIT 1")
    row = cur.fetchone()
    if not row:
        cur.execute(
            """
            INSERT INTO projects (name) VALUES ('t_proj') RETURNING id
            """
        )
        pid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO sources (project_id, title, source_type, location) "
            "VALUES (%s,'t','pdf','/tmp/x.pdf') RETURNING id",
            (pid,),
        )
        sid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO versions (source_id, version_no, sha256) VALUES (%s,1,'a') RETURNING id",
            (sid,),
        )
        vid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO atoms (version_id, document_id, atom_type, ordinal, content) "
            "VALUES (%s,%s,'text',1,'hello world test atom') RETURNING id",
            (vid, sid),
        )
        aid = cur.fetchone()[0]
        conn.commit()
    else:
        aid = row[0]
    with pytest.raises(psycopg2.Error):
        cur.execute(
            "INSERT INTO embeddings (atom_id, model, dims, vector, content_hash) "
            "VALUES (%s,'fake:hash-v1',768,'[0.1,0.2,0.3,0.4,0.5]','x')",
            (aid,),
        )
        conn.commit()
    conn.rollback()
    conn.close()


def test_unique_upsert(db_ready):
    conn = psycopg2.connect(db_ready)
    cur = conn.cursor()
    cur.execute("SELECT id FROM atoms LIMIT 1")
    aid = cur.fetchone()[0]
    v = "[" + ",".join(["0.01"] * 768) + "]"
    cur.execute(
        """
        INSERT INTO embeddings (atom_id, model, dims, vector, content_hash)
        VALUES (%s,'fake:hash-v1',768,%s::vector,'h1')
        ON CONFLICT (atom_id, model, dims) DO UPDATE SET content_hash='h2'
        """,
        (aid, v),
    )
    conn.commit()
    cur.execute(
        "SELECT content_hash FROM embeddings WHERE atom_id=%s AND model='fake:hash-v1'",
        (aid,),
    )
    assert cur.fetchone()[0] == "h2"
    conn.close()


def test_hnsw_index_present(db_ready):
    conn = psycopg2.connect(db_ready)
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM pg_indexes WHERE indexname='idx_emb_hnsw_fake_hash_v1_768'"
    )
    assert cur.fetchone()
    conn.close()
