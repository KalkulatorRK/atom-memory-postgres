#!/usr/bin/env python3
"""Импорт одного файла в разные проекты.

База берётся только из TEST_PG_DSN, никогда из PG_DSN: тест очищает таблицы,
и на рабочей базе это уничтожило бы данные. Шрифт — встроенный с кириллицей,
иначе текст превращается в точки и атомов не получается.
"""
import os
import sys
import tempfile
import unittest

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import import_document as im  # noqa: E402

DSN = os.environ.get("TEST_PG_DSN")
CALLS = {"n": 0}


def _fake_enrich(batch, doc_title="", prev_tail=""):
    CALLS["n"] += 1
    return [{**a, "metadata": {"tags": ["тест"], "page": a.get("page")}} for a in batch]


def _pdf(path, text):
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    # times-roman кириллицу не содержит — текст превращался в точки и атомов
    # не получалось. cjk её содержит.
    writer = fitz.TextWriter(page.rect)
    writer.append((50, 100), text + " " + ("слово " * 40), font=fitz.Font("cjk"))
    writer.write_text(page)
    doc.save(path)
    doc.close()


def _wipe():
    conn = psycopg2.connect(os.environ["PG_DSN"])
    cur = conn.cursor()
    cur.execute("TRUNCATE atom_links, journal, atoms, versions, sources, projects CASCADE")
    conn.commit()
    cur.close()
    conn.close()


def _projects():
    conn = psycopg2.connect(os.environ["PG_DSN"])
    cur = conn.cursor()
    cur.execute("SELECT name FROM projects ORDER BY name")
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


@unittest.skipUnless(DSN, "TEST_PG_DSN не задан — тест работает только на отдельной базе")
class ProjectConflictTests(unittest.TestCase):
    def setUp(self):
        os.environ["PG_DSN"] = DSN
        import importlib
        importlib.reload(im)
        im.enrich_batch = _fake_enrich
        CALLS["n"] = 0
        _wipe()

    def test_same_file_other_project_makes_no_llm_call(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            path = fh.name
        _pdf(path, "Документ А")
        im.import_doc(path, "alpha")
        before = CALLS["n"]
        self.assertGreater(before, 0, "первый импорт не вызвал обогащение")
        with self.assertRaises(SystemExit):
            im.import_doc(path, "beta")
        self.assertEqual(CALLS["n"], before)
        self.assertEqual(_projects(), ["alpha"])
        os.unlink(path)

    def test_changed_file_other_project_does_not_mix_versions(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            path = fh.name
        _pdf(path, "Документ А")
        im.import_doc(path, "alpha")
        _pdf(path, "Документ А, редакция 2")
        before = CALLS["n"]
        with self.assertRaises(SystemExit):
            im.import_doc(path, "beta")
        self.assertEqual(CALLS["n"], before)
        self.assertEqual(_projects(), ["alpha"])
        os.unlink(path)

    def test_new_file_new_project(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            path = fh.name
        _pdf(path, "Документ Б")
        im.import_doc(path, "gamma")
        self.assertGreater(CALLS["n"], 0)
        self.assertEqual(_projects(), ["gamma"])
        os.unlink(path)


if __name__ == "__main__":
    unittest.main()
