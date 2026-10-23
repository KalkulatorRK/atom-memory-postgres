"""Регрессии по ревью PR #1 (merge blockers)."""
import json
import os
import psycopg2
import pytest

from embeddings import resolve_provider
from search_core import _exact_match, search, search_fts_only
from vector_index import hnsw_index_name

pytestmark = pytest.mark.db


@pytest.fixture
def conn(db_ready):
    return psycopg2.connect(db_ready)


@pytest.fixture
def db_ready():
    from _db_guard import require
    from db_fixtures import get_test_dsn

    dsn = get_test_dsn()
    require(dsn, os.environ.get("PG_DSN", ""))
    return dsn


def _seed_atom(conn, content: str):
    import uuid

    loc = f"/pr1_{uuid.uuid4().hex}.pdf"
    cur = conn.cursor()
    cur.execute("SELECT id FROM projects LIMIT 1")
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO projects (name) VALUES ('pr1_test') RETURNING id")
        pid = cur.fetchone()[0]
    else:
        pid = row[0]
    cur.execute(
        "INSERT INTO sources (project_id, title, source_type, location) "
        "VALUES (%s,'T','pdf',%s) RETURNING id",
        (pid, loc),
    )
    sid = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO versions (source_id, version_no, sha256) VALUES (%s,1,'x') RETURNING id",
        (sid,),
    )
    vid = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO atoms (version_id, document_id, atom_type, ordinal, content, metadata) "
        "VALUES (%s,%s,'text',1,%s,'{}'::jsonb) RETURNING id",
        (vid, sid, content),
    )
    aid = cur.fetchone()[0]
    conn.commit()
    cur.close()
    return aid


@pytest.mark.parametrize(
    "query,meta,needle",
    [
        ("ст. 475", {"article": "475", "doc_kind": "code", "law": "ГК РФ"}, "475"),
        (
            "ГОСТ 7512-82",
            {"standard": "ГОСТ 7512-82", "doc_kind": "gost"},
            "7512-82",
        ),
        (
            "п. 2 ст. 475",
            {"article": "475", "point": "2", "doc_kind": "code", "law": "ГК РФ"},
            "пункт два",
        ),
        ("ст. 12", {"article": "12", "doc_kind": "code", "law": "ГК РФ"}, "12"),
        (
            "v11",
            {"article": "475", "doc_kind": "code", "law": "ГК РФ", "redaction": "v11"},
            "v11",
        ),
    ],
)
def test_hybrid_identifier_exact_tier_ranks_first(conn, query, meta, needle):
    import uuid

    proj = f"pr1_rank_{uuid.uuid4().hex[:10]}"
    loc = f"/rank_{uuid.uuid4().hex}.pdf"
    cur = conn.cursor()
    cur.execute("INSERT INTO projects (name) VALUES (%s) RETURNING id", (proj,))
    pid = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO sources (project_id, title, source_type, location) "
        "VALUES (%s,'T','pdf',%s) RETURNING id",
        (pid, loc),
    )
    sid = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO versions (source_id, version_no, sha256) VALUES (%s,1,'x') RETURNING id",
        (sid,),
    )
    vid = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO atoms (version_id, document_id, atom_type, ordinal, content, metadata) "
        "VALUES (%s,%s,'text',1,'шум без совпадений xyz','{}'::jsonb)",
        (vid, sid),
    )
    cur.execute(
        "INSERT INTO atoms (version_id, document_id, atom_type, ordinal, content, metadata) "
        "VALUES (%s,%s,'text',2,%s,%s::jsonb) RETURNING id",
        (
            vid,
            sid,
            f"статья 475 ГОСТ 7512-82 v11 номер 12 {needle}",
            json.dumps(meta, ensure_ascii=False),
        ),
    )
    target_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    sr = search(
        conn,
        query,
        project=proj,
        limit=5,
        mode="hybrid",
        provider=None,
        provider_warnings=["вектор выключен для теста"],
    )
    assert sr.results, f"no hits for {query!r}"
    assert sr.results[0].atom_id == target_id
    if query in ("ГОСТ 7512-82", "v11"):
        assert sr.results[0].exact is False
    else:
        assert sr.results[0].exact is True


def test_exact_match_python_word_boundaries():
    from search_core import parse_structured_query

    sq = parse_structured_query("ст. 475")
    assert _exact_match("текст ст. 475 далее", {"article": "475"}, sq)


def test_hnsw_index_name_matches_migration():
    assert hnsw_index_name("cloud:text-embedding-3-small", 768) == "idx_emb_hnsw_cloud_te3s_768"
    assert hnsw_index_name("fake:hash-v1", 768) == "idx_emb_hnsw_fake_hash_v1_768"


def test_mcp_fts_mode_with_hits(conn):
    _seed_atom(conn, "уникальный термин pr1blocker xyz контроль")
    sr = search_fts_only(conn, "pr1blocker", limit=5)
    assert len(sr.results) >= 1


def test_mcp_json_compat_shape():
    from memory_mcp_server import format_memory_search_response

    res = [{"id": 1, "content": "x"}]
    assert format_memory_search_response(res, []).startswith("[")
    assert format_memory_search_response(res, ["vector off"]).startswith("[")
    wrapped = json.loads(format_memory_search_response([], ["warn"], include_warnings=True))
    assert wrapped["warnings"] == ["warn"]


def test_resolve_provider_uses_passed_env_not_os(monkeypatch):
    monkeypatch.setenv("EMBED_API_KEY", "from-os-should-not-use")
    p, _ = resolve_provider({"EMBED_PROVIDER": "none"})
    assert p is None
    p2, _ = resolve_provider({"EMBED_PROVIDER": "fake", "EMBED_API_KEY": ""})
    assert p2 is not None


def test_setup_password_sql_injection_safe():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "setup_memory_db.sh")
    text = open(script, encoding="utf-8").read()
    assert "PASSWORD '${DB_PASS}'" not in text
    assert "render_role_password_sql.py" in text
    assert "set_db_role_password()" in text
    assert "-v db_pass=" not in text


def test_vector_admin_script_single_psql_session():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(root, "vector_index_admin.sh"), encoding="utf-8").read()
    assert "CREATE INDEX CONCURRENTLY" in text
    assert "SET maintenance_work_mem" in text
    assert 'psql_admin "$DB" -v ON_ERROR_STOP=1' in text
    assert 'psql_admin "$DB" -v ON_ERROR_STOP=1 -c "SET maintenance_work_mem' not in text


def test_migration_down_removes_journal(db_ready):
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
        conn = psycopg2.connect(db_ready)
        cur = conn.cursor()
        cur.execute(
            "SELECT count(*) FROM journal WHERE op_type='migration' "
            "AND details->>'name'='0004_vector_search'"
        )
        assert cur.fetchone()[0] == 0
        conn.close()
    finally:
        apply_sql_file(admin_db, up)


def test_embed_policy_restored_after_down_and_reapply(db_ready):
    if not os.environ.get("ADMIN_DSN"):
        pytest.skip("ADMIN_DSN")
    from pathlib import Path

    from migration_admin import admin_dsn_for_test_db, apply_sql_file

    root = Path(__file__).resolve().parents[2]
    admin_db = admin_dsn_for_test_db(db_ready)
    down = root / "references/migrations/0004_vector_search_down.sql"
    up = root / "references/migrations/0004_vector_search.sql"
    conn = psycopg2.connect(db_ready)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO projects (name, embed_policy) VALUES ('pr1_pol_snap', 'local_only') "
        "ON CONFLICT (name) DO UPDATE SET embed_policy = EXCLUDED.embed_policy "
        "RETURNING id"
    )
    pid = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    try:
        apply_sql_file(admin_db, down)
        apply_sql_file(admin_db, up)
        conn = psycopg2.connect(db_ready)
        cur = conn.cursor()
        cur.execute("SELECT embed_policy FROM projects WHERE id = %s", (pid,))
        assert cur.fetchone()[0] == "local_only"
        conn.close()
    finally:
        apply_sql_file(admin_db, up)
