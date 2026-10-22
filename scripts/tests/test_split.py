#!/usr/bin/env python3
"""Тесты нарезки и сборки запроса. БД не нужна."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from import_document import smart_split, quality_gate  # noqa: E402
from _common import fts_query  # noqa: E402


def test_page_survives_split():
    text = ("<!-- страница 2 --> Первое предложение достаточно длинное, чтобы пройти "
            "фильтр. Второе тоже несёт смысл и номер страницы не должен потеряться.")
    atoms = smart_split(text)
    assert atoms, "нарезка вернула пусто"
    assert all(a["page"] == 2 for a in atoms), [a["page"] for a in atoms]


def test_page_advances_between_chunks():
    long = "Предложение номер один содержит достаточно текста для атома. " * 30
    text = f"<!-- страница 1 --> {long}\n\n<!-- страница 2 --> {long}"
    atoms = smart_split(text)
    pages = {a["page"] for a in atoms}
    assert pages == {1, 2}, pages


def test_quality_gate_strips_marker_keeps_page():
    atoms = [{"content": "<!-- страница 4 --> Текст с буквами достаточной длины для фильтра.",
              "atom_type": "text", "page": None}]
    clean, dropped = quality_gate(atoms)
    assert dropped == 0
    assert "страница" not in clean[0]["content"]
    assert clean[0]["page"] == 4


def test_quality_gate_drops_garbage():
    atoms = [{"content": "123 45", "atom_type": "text"}]
    clean, dropped = quality_gate(atoms)
    assert dropped == 1 and clean == []


def test_fts_query_uses_or_and_drops_stopwords():
    q = fts_query("какие требования к чувствительности контроля")
    assert " & " not in q
    assert " | " in q
    assert "какие" not in q
    assert "чувствительности" in q


def test_page_boundary_does_not_roll_back():
    """Атом на стыке страниц цитирует страницу начала, а следующий за ним
    не откатывается на предыдущую."""
    head = "Предложение достаточно длинное для отдельного атома. " * 12
    tail = "Продолжение на следующей странице тоже длинное. " * 12
    text = f"<!-- страница 1 --> {head}\n\n<!-- страница 2 --> {tail}"
    atoms = smart_split(text)
    # атом, начатый на стр.1 и содержащий маркер стр.2, остаётся стр.1
    crossing = [a for a in atoms if "страница 2" in a["content"]]
    assert crossing and crossing[0]["page"] == 1, [a["page"] for a in crossing]
    # всё, что целиком после маркера стр.2, — страница 2, не 1
    after = atoms[atoms.index(crossing[0]) + 1:]
    assert after and all(a["page"] == 2 for a in after), [a["page"] for a in after]


def test_fts_query_empty_is_safe():
    assert fts_query("что как по") == "''"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
