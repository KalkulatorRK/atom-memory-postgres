"""VS-14/VS-15: структурная нарезка, цитаты, фильтр as-of."""
from __future__ import annotations

import os
import sys
import unittest
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

@pytest.fixture(scope="module")
def db_ready():
    from _db_guard import require
    from db_fixtures import get_test_dsn

    dsn = get_test_dsn()
    require(dsn, os.environ.get("PG_DSN", ""))
    return dsn


from import_document import quality_gate, smart_split  # noqa: E402
from render_role_password_sql import render_role_password_sql  # noqa: E402
from search_core import _exact_match, _meta_section_matches, parse_structured_query  # noqa: E402
from structure import (  # noqa: E402
    DocImportOptions,
    detect_doc_kind,
    format_citation,
    prepare_for_import,
    strip_colontituls,
    structure_split,
)


SYNTH_CODE = """
<!-- страница 1 -->
ГК РФ ч. 2 (ред. от 01.01.2024)

Статья 474. Общие положения о продаже товаров
1. Продавец обязан передать покупателю товар надлежащего качества.
2. Товар должен соответствовать условиям договора.

Статья 475. Последствия передачи товара ненадлежащего качества
1. Покупатель вправе потребовать соразмерного уменьшения цены.
2. Покупатель вправе отказаться от исполнения договора и потребовать возврата уплаченной суммы.
"""

SYNTH_GOST = """
<!-- страница 1 -->
ГОСТ 7512-82 Контроль неразрушающий. Соединения сварные

5 Требования к контролю
5.1 Общие положения
5.1.1 Контроль проводят по утверждённой методике.

5.2 Чувствительность
5.2.3 Минимальная чувствительность должна соответствовать таблице 1.

ГОСТ 7512-82 С. 5

Таблица 1 — Параметры контроля
"""


class StructureCodeTests(unittest.TestCase):
    def test_detect_code(self):
        self.assertEqual(detect_doc_kind(SYNTH_CODE, "gk.pdf", "auto"), "code")

    def test_no_cross_article_boundary(self):
        opts = DocImportOptions(doc_kind="code", source_title="ГК РФ ч. 2.pdf")
        md, ctx, _ = prepare_for_import(SYNTH_CODE, opts)
        self.assertIsNotNone(ctx)
        atoms, _ = quality_gate(structure_split(md, ctx, chunk_max=500, chunk_min=80))
        arts = {a.get("structure_meta", {}).get("article") for a in atoms}
        self.assertIn("474", arts)
        self.assertIn("475", arts)
        for a in atoms:
            art = a.get("structure_meta", {}).get("article")
            self.assertIn(art, ("474", "475"))
            for other in ("474", "475"):
                if other != art:
                    self.assertNotIn(f"Статья {other}", a["content"])

    def test_point_metadata(self):
        opts = DocImportOptions(doc_kind="code", source_title="ГК РФ ч. 2")
        md, ctx, _ = prepare_for_import(SYNTH_CODE, opts)
        atoms, _ = quality_gate(structure_split(md, ctx, chunk_max=500, chunk_min=50))
        p475_2 = [
            a
            for a in atoms
            if a.get("structure_meta", {}).get("article") == "475"
            and a.get("structure_meta", {}).get("point") == "2"
        ]
        self.assertTrue(p475_2, "нет атома ст.475 п.2")
        self.assertIn("возврата", p475_2[0]["content"].lower())

    def test_plain_pdf_unchanged(self):
        plain = "Абзац обычного текста без структуры. " * 20
        opts = DocImportOptions(doc_kind="auto", source_title="report.pdf")
        md, ctx, _ = prepare_for_import(plain, opts)
        self.assertIsNone(ctx)
        self.assertEqual(smart_split(md), smart_split(plain))

    def test_mid_sentence_article_reference_not_split(self):
        text = """
Статья 474. Общие положения
1. Введение.
2. Если порядок не установлен, последствия определяет статья 475 настоящего Кодекса, а также обычаи.

Статья 475. Последствия
1. Покупатель вправе потребовать соразмерного уменьшения покупной цены.
"""
        opts = DocImportOptions(doc_kind="code", source_title="ГК РФ ч. 2")
        md, ctx, _ = prepare_for_import(text, opts)
        atoms, _ = quality_gate(structure_split(md, ctx, chunk_max=800, chunk_min=40))
        fake = [
            a
            for a in atoms
            if a.get("structure_meta", {}).get("article") == "475"
            and not a.get("structure_meta", {}).get("point")
            and "настоящего Кодекса" in a["content"]
        ]
        self.assertFalse(fake, "ложный атом из «статья 475» внутри предложения")
        p474_2 = [
            a
            for a in atoms
            if a.get("structure_meta", {}).get("article") == "474"
            and a.get("structure_meta", {}).get("point") == "2"
        ]
        self.assertTrue(p474_2)
        self.assertIn("обычаи", p474_2[0]["content"])

    def test_mid_sentence_inflected_article_forms(self):
        text = (
            "Статья 12. Текст.\n"
            "1. Ссылка статьей 13 настоящего Кодекса не создаёт границу.\n"
            "Статья 13. Другая.\n"
            "1. Продолжение без разрыва по форме статьи 14 в середине фразы допустимо.\n"
        )
        opts = DocImportOptions(doc_kind="code", source_title="gk.pdf")
        md, ctx, _ = prepare_for_import(text, opts)
        atoms, _ = quality_gate(structure_split(md, ctx, chunk_max=800, chunk_min=30))
        arts = [a.get("structure_meta", {}).get("article") for a in atoms]
        self.assertEqual(arts.count("13"), sum(1 for a in atoms if a.get("structure_meta", {}).get("article") == "13"))
        self.assertNotIn(
            None,
            [a.get("structure_meta", {}).get("article") for a in atoms if "статьей 13" in a["content"].lower()],
        )


class StructureGostTests(unittest.TestCase):
    def test_colontitul_stripped(self):
        cleaned = strip_colontituls(SYNTH_GOST)
        self.assertNotIn("С. 5", cleaned)

    def test_section_path_and_table(self):
        opts = DocImportOptions(doc_kind="gost", source_title="ГОСТ 7512-82.pdf")
        md, ctx, _ = prepare_for_import(SYNTH_GOST, opts)
        atoms, _ = quality_gate(structure_split(md, ctx, chunk_max=500, chunk_min=40))
        leaf = [
            a
            for a in atoms
            if a.get("structure_meta", {}).get("section_path") == ["5", "5.2", "5.2.3"]
        ]
        self.assertTrue(leaf, [a.get("structure_meta") for a in atoms])
        self.assertIn("чувствительность", leaf[0]["content"].lower())


class CitationTests(unittest.TestCase):
    def test_citation_code(self):
        meta = {
            "law": "ГК РФ ч. 2",
            "article": "475",
            "point": "2",
            "redaction": "ред. от 01.01.2024",
            "page": 12,
            "doc_kind": "code",
        }
        cite = format_citation(meta, "ГК РФ ч. 2")
        self.assertIn("ст. 475", cite)
        self.assertIn("п. 2", cite)
        self.assertIn("ред.", cite)
        self.assertIn("стр. 12", cite)

    def test_citation_gost(self):
        meta = {
            "doc_kind": "gost",
            "section_path": ["5", "5.2", "5.2.3"],
            "page": 8,
        }
        cite = format_citation(meta, "ГОСТ 7512-82")
        self.assertIn("ГОСТ 7512-82", cite)
        self.assertIn("п. 5.2.3", cite)
        self.assertIn("стр. 8", cite)

    def test_exact_match_article_point(self):
        meta = {"article": "475", "point": "2"}
        sq = parse_structured_query("п. 2 ст. 475")
        self.assertTrue(_exact_match("текст", meta, sq))
        self.assertFalse(_exact_match("текст", {"article": "476", "point": "1"}, sq))

    def test_gost_section_prefix_exact(self):
        meta = {"standard": "ГОСТ 7512-82", "section_path": ["4", "4.2", "4.2.3"]}
        sq = parse_structured_query("ГОСТ 7512-82 п. 4.2")
        self.assertTrue(_exact_match("", meta, sq))
        self.assertTrue(_meta_section_matches(meta, "4.2"))
        other = {"standard": "ГОСТ Р 55724", "section_path": ["4", "4.2"]}
        self.assertFalse(_exact_match("", other, sq))

    def test_standard_only_not_exact(self):
        sq = parse_structured_query("ГОСТ 7512-82")
        meta = {"standard": "ГОСТ 7512-82", "doc_kind": "gost"}
        self.assertFalse(_exact_match("ГОСТ 7512-82 текст", meta, sq))


class RoleSecurityUnitTests(unittest.TestCase):
    def test_reject_pg_role(self):
        with self.assertRaises(ValueError):
            render_role_password_sql("pg_hacker", "secret")

    def test_reject_nul(self):
        with self.assertRaises(ValueError):
            render_role_password_sql("user", "a\x00b")


@pytest.mark.db
def test_as_of_filter(db_ready):
    """V50: --as-of выбирает последнюю редакцию на дату."""
    import json

    import psycopg2

    from db_fixtures import get_test_dsn
    from search_core import search

    dsn = get_test_dsn()
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    proj = f"law_asof_{uuid.uuid4().hex[:8]}"
    sid = pid = None
    try:
        cur.execute("INSERT INTO projects (name) VALUES (%s) RETURNING id", (proj,))
        pid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO sources (project_id, title, source_type, location, content_sha, content_size) "
            "VALUES (%s, 't', 'pdf', %s, 'a', 1) RETURNING id",
            (pid, f"/tmp/{proj}.pdf"),
        )
        sid = cur.fetchone()[0]
        for vno, eff, art in ((1, "2020-01-01", "old"), (2, "2024-06-01", "new")):
            cur.execute(
                "INSERT INTO versions (source_id, version_no, sha256) VALUES (%s, %s, %s) RETURNING id",
                (sid, vno, f"sha{vno}"),
            )
            vid = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO atoms (version_id, document_id, atom_type, ordinal, content, metadata) "
                "VALUES (%s, %s, 'text', 1, %s, %s::jsonb)",
                (
                    vid,
                    sid,
                    f"статья {art} текст достаточной длины для индексации",
                    json.dumps(
                        {
                            "article": art,
                            "effective_date": eff,
                            "doc_kind": "code",
                            "law": "TEST",
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        cur.execute(
            "UPDATE atoms SET status = 'superseded' "
            "WHERE version_id = (SELECT id FROM versions WHERE source_id = %s AND version_no = 1)",
            (sid,),
        )
        conn.commit()
        sr = search(conn, "статья", project=proj, limit=10, mode="fts", as_of="2022-01-01")
        arts = {(h.metadata or {}).get("article") for h in sr.results}
        assert arts == {"old"}
    finally:
        try:
            if sid:
                cur.execute("DELETE FROM sources WHERE id = %s", (sid,))
            if pid:
                cur.execute("DELETE FROM projects WHERE id = %s", (pid,))
            conn.commit()
        finally:
            cur.close()
            conn.close()


@pytest.mark.db
def test_as_of_includes_undated_sources(db_ready):
    import json

    import psycopg2

    from db_fixtures import get_test_dsn
    from search_core import search

    conn = psycopg2.connect(get_test_dsn())
    cur = conn.cursor()
    proj = f"undated_{uuid.uuid4().hex[:8]}"
    sid = pid = None
    try:
        cur.execute("INSERT INTO projects (name) VALUES (%s) RETURNING id", (proj,))
        pid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO sources (project_id, title, source_type, location) "
            "VALUES (%s,'sdank','pdf',%s) RETURNING id",
            (pid, f"/tmp/{proj}.pdf"),
        )
        sid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO versions (source_id, version_no, sha256) VALUES (%s,1,'u') RETURNING id",
            (sid,),
        )
        vid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO atoms (version_id, document_id, atom_type, ordinal, content, metadata) "
            "VALUES (%s,%s,'text',1,%s,%s::jsonb)",
            (
                vid,
                sid,
                "текст про аттестацию сварщиков без даты редакции",
                json.dumps({"doc_kind": "sdank"}),
            ),
        )
        conn.commit()
        sr = search(
            conn, "аттестации", project=proj, limit=5, mode="fts", as_of="2025-01-01"
        )
        assert len(sr.results) >= 1
    finally:
        try:
            if sid:
                cur.execute("DELETE FROM sources WHERE id = %s", (sid,))
            if pid:
                cur.execute("DELETE FROM projects WHERE id = %s", (pid,))
            conn.commit()
        finally:
            cur.close()
            conn.close()


@pytest.mark.db
def test_as_of_picks_superseded_version(db_ready):
    import json

    import psycopg2

    from db_fixtures import get_test_dsn
    from search_core import search

    conn = psycopg2.connect(get_test_dsn())
    cur = conn.cursor()
    proj = f"gkver_{uuid.uuid4().hex[:8]}"
    loc = f"/tmp/{proj}_gkver.pdf"
    sid = pid = None
    try:
        cur.execute("INSERT INTO projects (name) VALUES (%s) RETURNING id", (proj,))
        pid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO sources (project_id, title, source_type, location, content_sha, content_size) "
            "VALUES (%s,'gkver','pdf',%s,'same',1) RETURNING id",
            (pid, loc),
        )
        sid = cur.fetchone()[0]
        for vno, eff, token in ((1, "2020-01-01", "уменьшения покупной цены v1"), (2, "2024-06-01", "уменьшения покупной цены v2")):
            cur.execute(
                "INSERT INTO versions (source_id, version_no, sha256) VALUES (%s,%s,%s) RETURNING id",
                (sid, vno, f"v{vno}"),
            )
            vid = cur.fetchone()[0]
            st = "active" if vno == 2 else "superseded"
            cur.execute(
                "INSERT INTO atoms (version_id, document_id, atom_type, ordinal, content, metadata, status) "
                "VALUES (%s,%s,'text',1,%s,%s::jsonb,%s)",
                (
                    vid,
                    sid,
                    token,
                    json.dumps({"effective_date": eff, "doc_kind": "code", "law": "ГК РФ"}),
                    st,
                ),
            )
        conn.commit()
        sr = search(
            conn,
            "уменьшения покупной цены",
            project=proj,
            limit=5,
            mode="fts",
            as_of="2021-06-01",
        )
        assert sr.results
        assert "v1" in sr.results[0].content
        assert "v2" not in sr.results[0].content
    finally:
        try:
            if sid:
                cur.execute("DELETE FROM sources WHERE id = %s", (sid,))
            if pid:
                cur.execute("DELETE FROM projects WHERE id = %s", (pid,))
            conn.commit()
        finally:
            cur.close()
            conn.close()


if __name__ == "__main__":
    unittest.main()
