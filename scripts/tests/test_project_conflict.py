#!/usr/bin/env python3
"""Импорт одного файла в разные проекты.

База берётся только из TEST_PG_DSN. Тест очищает таблицы, поэтому отказывается
запускаться на чём-то, кроме выделенной тестовой базы: TEST_PG_DSN должен
отличаться от PG_DSN и указывать на базу с именем, содержащим «test».
"""
import os
import sys
import tempfile
import unittest
from urllib.parse import urlparse

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import import_document as im  # noqa: E402

DSN = os.environ.get("TEST_PG_DSN")
CALLS = {"n": 0}


def _dbname(dsn):
    return urlparse(dsn).path.lstrip("/")


def _safe():
    if not DSN:
        return False
    if os.environ.get("PG_DSN") and DSN == os.environ["PG_DSN"]:
        return False
    return "test" in _dbname(DSN).lower()


def _fake_enrich(batch, doc_title="", prev_tail=""):
    CALLS["n"] += 1
    return [{**a, "metadata": {"tags": ["тест"], "page": a.get("page")}} for a in batch]


def _pdf(path, text):
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    writer = fitz.TextWriter(page.rect)
    writer.append((50, 100), text + " " + ("слово " * 40), font=fitz.Font("cjk"))
    writer.write_text(page)
    doc.save(path)
    doc.close()


def _wipe():
    conn = psycopg2.connect(os.environ["PG_DSN"])
    cur = conn.cursor()
    cur.execute("DELETE FROM atom_links; DELETE FROM journal; DELETE FROM atoms; "
                "DELETE FROM versions; DELETE FROM sources; DELETE FROM projects;")
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


@unittest.skipUnless(_safe(), "нужен TEST_PG_DSN на отдельной базе с «test» в имени")
class ProjectConflictTests(unittest.TestCase):
    def setUp(self):
        self._old_pg = os.environ.get("PG_DSN")
        os.environ["PG_DSN"] = DSN
        import importlib
        importlib.reload(im)
        im.enrich_batch = _fake_enrich
        CALLS["n"] = 0
        _wipe()

    def tearDown(self):
        if self._old_pg is None:
            os.environ.pop("PG_DSN", None)
        else:
            os.environ["PG_DSN"] = self._old_pg
        import importlib
        importlib.reload(im)

    def test_same_file_other_project_makes_no_llm_call(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            path = fh.name
        try:
            _pdf(path, "Документ А")
            im.import_doc(path, "alpha")
            before = CALLS["n"]
            self.assertGreater(before, 0, "первый импорт не вызвал обогащение")
            with self.assertRaises(SystemExit):
                im.import_doc(path, "beta")
            self.assertEqual(CALLS["n"], before)
            self.assertEqual(_projects(), ["alpha"])
        finally:
            os.unlink(path)

    def test_changed_file_other_project_does_not_mix_versions(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            path = fh.name
        try:
            _pdf(path, "Документ А")
            im.import_doc(path, "alpha")
            _pdf(path, "Документ А, редакция 2")
            before = CALLS["n"]
            with self.assertRaises(SystemExit):
                im.import_doc(path, "beta")
            self.assertEqual(CALLS["n"], before)
            self.assertEqual(_projects(), ["alpha"])
        finally:
            os.unlink(path)

    def test_new_file_new_project(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            path = fh.name
        try:
            _pdf(path, "Документ Б")
            im.import_doc(path, "gamma")
            self.assertGreater(CALLS["n"], 0)
            self.assertEqual(_projects(), ["gamma"])
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()