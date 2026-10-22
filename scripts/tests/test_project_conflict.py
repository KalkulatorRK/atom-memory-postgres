#!/usr/bin/env python3
"""Импорт одного файла в разные проекты. БД — тестовая, LLM не вызывается.

Кейсы: тот же файл в другой проект, изменённый файл в другой проект,
новый файл в новый проект. В первых двух — ноль вызовов LLM и ни одного
пустого проекта.
"""
import importlib
import os
import sys
import tempfile

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import import_document as im  # noqa: E402

DSN = os.environ.get("PG_DSN")
calls = {"n": 0}


def fake_enrich(batch, doc_title="", prev_tail=""):
    calls["n"] += 1
    return [{**a, "metadata": {"tags": ["тест"], "page": a.get("page")}} for a in batch]


def reset():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    for table in ("atom_links", "journal", "atoms", "versions", "sources", "projects"):
        cur.execute(f"DELETE FROM {table}")
    conn.commit()
    cur.close()
    conn.close()
    calls["n"] = 0


def projects():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT name FROM projects ORDER BY name")
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def run():
    im.enrich_batch = fake_enrich
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
        path = fh.name
    try:
        _pdf(path, "Документ А")
        reset()

        im.import_doc(path, "alpha")
        assert projects() == ["alpha"], projects()

        # тот же файл в другой проект: ошибка до LLM, проектов не прибавляется
        before = calls["n"]
        try:
            im.import_doc(path, "beta")
            raise AssertionError("ожидалась ошибка")
        except SystemExit as e:
            assert "alpha" in str(e), e
        assert calls["n"] == before, "LLM вызвался зря"
        assert projects() == ["alpha"], projects()

        # изменённый файл в другой проект: тоже ошибка, версии не плодятся
        _pdf(path, "Документ А, редакция 2")
        before = calls["n"]
        try:
            im.import_doc(path, "beta")
            raise AssertionError("ожидалась ошибка на изменённом файле")
        except SystemExit:
            pass
        assert calls["n"] == before
        assert projects() == ["alpha"], projects()

        # новый файл в новый проект — проходит
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh2:
            path2 = fh2.name
        _pdf(path2, "Документ Б")
        im.import_doc(path2, "beta")
        assert projects() == ["alpha", "beta"], projects()
        os.unlink(path2)
        print("ok  project conflicts")
    finally:
        os.unlink(path)


def _pdf(path, text):
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), text + " " + ("слово " * 40))
    doc.save(path)
    doc.close()


if __name__ == "__main__":
    if not DSN:
        print("skip: PG_DSN не задан")
        sys.exit(0)
    run()
