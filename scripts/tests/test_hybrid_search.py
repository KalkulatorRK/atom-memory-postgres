import os

import psycopg2
import pytest

from embeddings import FakeEmbeddingProvider
from search_core import extract_identifiers, rrf_score, search
from _db_guard import require
from db_fixtures import get_test_dsn

pytestmark = pytest.mark.db


def test_rrf_math():
    ranks = {"fts": 1, "vector": 2}
    s = rrf_score(ranks, {"fts": 1.0, "vector": 1.0}, k=60)
    assert abs(s - (1 / 61 + 1 / 62)) < 1e-9


def test_exact_identifier_tier():
    ids = extract_identifiers("ГОСТ 7512-82 ст. 475")
    assert any(t == "standard" for t, _ in ids)


@pytest.fixture
def seeded_db(monkeypatch):
    syn = os.path.join(os.path.dirname(__file__), "fixtures", "fake_synonyms.json")
    monkeypatch.setenv("EMBED_FAKE_SYNONYMS", syn)
    dsn = get_test_dsn()
    require(dsn, os.environ.get("PG_DSN", ""))
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute("DELETE FROM atom_links")
    cur.execute("DELETE FROM embeddings")
    cur.execute("DELETE FROM atoms")
    cur.execute("DELETE FROM versions")
    cur.execute("DELETE FROM sources")
    cur.execute("DELETE FROM projects")
    cur.execute("INSERT INTO projects (name) VALUES ('p1') RETURNING id")
    pid = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO sources (project_id, title, source_type, location) "
        "VALUES (%s,'Doc','pdf','/x.pdf') RETURNING id",
        (pid,),
    )
    sid = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO versions (source_id, version_no, sha256) VALUES (%s,1,'s') RETURNING id",
        (sid,),
    )
    vid = cur.fetchone()[0]
    texts = [
        ("ГОСТ 7512-82 метод контроля", "text"),
        ("товар ненадлежащего качества возврат", "text"),
    ]
    aids = []
    for i, (txt, at) in enumerate(texts, 1):
        cur.execute(
            "INSERT INTO atoms (version_id, document_id, atom_type, ordinal, content, metadata) "
            "VALUES (%s,%s,%s,%s,%s,'{}'::jsonb) RETURNING id",
            (vid, sid, at, i, txt),
        )
        aids.append(cur.fetchone()[0])
    conn.commit()
    fp = FakeEmbeddingProvider()
    for aid, (txt, _) in zip(aids, texts):
        vec = fp.embed_passages([txt])[0]
        cur.execute(
            "INSERT INTO embeddings (atom_id, model, dims, vector, content_hash) "
            "VALUES (%s,'fake:hash-v1',768,%s,'h')",
            (aid, vec),
        )
    conn.commit()
    yield conn, aids
    conn.close()


def test_hybrid_finds_paraphrase(seeded_db):
    conn, aids = seeded_db
    sr = search(conn, "бракованный товар", limit=5, mode="hybrid")
    assert sr.results
    contents = " ".join(h.content for h in sr.results)
    assert "ненадлежащего" in contents or "ГОСТ" in contents


def test_query_count_constant(seeded_db):
    conn, _ = seeded_db
    for lim in (3, 10, 20):
        sr = search(conn, "качество", limit=lim, mode="hybrid")
        assert len(sr.results) <= lim
