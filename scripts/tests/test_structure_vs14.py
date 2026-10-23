"""VS-14/VS-15: структурная нарезка, цитаты, фильтр as-of."""
from __future__ import annotations

import os
import sys
import unittest
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from import_document import quality_gate, smart_split  # noqa: E402
from render_role_password_sql import render_role_password_sql  # noqa: E402
from search_core import _exact_match, extract_identifiers, search  # noqa: E402
from structure import (  # noqa: E402
    DocImportOptions,
    StructureContext,
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
        ids = extract_identifiers("п. 2 ст. 475")
        self.assertTrue(_exact_match("текст", meta, ids))


class RoleSecurityUnitTests(unittest.TestCase):
    def test_reject_pg_role(self):
        with self.assertRaises(ValueError):
            render_role_password_sql("pg_hacker", "secret")

    def test_reject_nul(self):
        with self.assertRaises(ValueError):
            render_role_password_sql("user", "a\x00b")


@pytest.mark.db
def test_as_of_filter(db_ready):
    """V50: --as-of отсекает атомы с более поздней effective_date."""
    import json

    import psycopg2

    from db_fixtures import get_test_dsn
    from search_core import search

    dsn = get_test_dsn()
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    proj = f"law_asof_{uuid.uuid4().hex[:8]}"
    cur.execute("INSERT INTO projects (name) VALUES (%s) RETURNING id", (proj,))
    pid = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO sources (project_id, title, source_type, location, content_sha, content_size) "
        "VALUES (%s, 't', 'pdf', %s, 'a', 1) RETURNING id",
        (pid, f"/tmp/{proj}.pdf"),
    )
    sid = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO versions (source_id, version_no, sha256) VALUES (%s, 1, 'a') RETURNING id",
        (sid,),
    )
    vid = cur.fetchone()[0]
    for eff, art in (("2020-01-01", "old"), ("2024-06-01", "new")):
        cur.execute(
            "INSERT INTO atoms (version_id, document_id, atom_type, ordinal, content, metadata) "
            "VALUES (%s, %s, 'text', %s, %s, %s::jsonb)",
            (
                vid,
                sid,
                1 if art == "old" else 2,
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
    conn.commit()
    sr = search(conn, "статья", project=proj, limit=10, mode="fts", as_of="2022-01-01")
    arts = {(h.metadata or {}).get("article") for h in sr.results}
    assert arts == {"old"}
    cur.execute("DELETE FROM sources WHERE id = %s", (sid,))
    cur.execute("DELETE FROM projects WHERE id = %s", (pid,))
    conn.commit()
    cur.close()
    conn.close()


if __name__ == "__main__":
    unittest.main()
