#!/usr/bin/env python3
"""Тесты нарезки и сборки запроса. БД не нужна."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from import_document import smart_split, quality_gate  # noqa: E402
from _common import fts_query  # noqa: E402


class SplitTests(unittest.TestCase):
    def test_page_survives_split(self):
        text = ("<!-- страница 2 --> Первое предложение достаточно длинное, чтобы пройти "
                "фильтр. Второе тоже несёт смысл и номер страницы не должен потеряться.")
        atoms = smart_split(text)
        self.assertTrue(atoms, "нарезка вернула пусто")
        self.assertTrue(all(a["page"] == 2 for a in atoms), [a["page"] for a in atoms])

    def test_page_advances_between_chunks(self):
        long = "Предложение номер один содержит достаточно текста для атома. " * 30
        text = f"<!-- страница 1 --> {long}\n\n<!-- страница 2 --> {long}"
        atoms = smart_split(text)
        pages = {a["page"] for a in atoms}
        self.assertEqual(pages, {1, 2})

    def test_quality_gate_strips_marker_keeps_page(self):
        atoms = [{"content": "<!-- страница 4 --> Текст с буквами достаточной длины для фильтра.",
                  "atom_type": "text", "page": None}]
        clean, dropped = quality_gate(atoms)
        self.assertEqual(dropped, 0)
        self.assertNotIn("страница", clean[0]["content"])
        self.assertEqual(clean[0]["page"], 4)

    def test_quality_gate_drops_garbage(self):
        atoms = [{"content": "123 45", "atom_type": "text"}]
        clean, dropped = quality_gate(atoms)
        self.assertEqual(dropped, 1)
        self.assertEqual(clean, [])

    def test_fts_query_uses_or_and_drops_stopwords(self):
        q = fts_query("какие требования к чувствительности контроля")
        self.assertNotIn(" & ", q)
        self.assertIn(" | ", q)
        self.assertNotIn("какие", q)
        self.assertIn("чувствительности", q)

    def test_fts_query_empty_is_safe(self):
        self.assertIsNone(fts_query("что как по"))

    def test_page_boundary_does_not_roll_back(self):
        head = "Предложение достаточно длинное для отдельного атома. " * 12
        tail = "Продолжение на следующей странице тоже длинное. " * 12
        text = f"<!-- страница 1 --> {head}\n\n<!-- страница 2 --> {tail}"
        atoms = smart_split(text)
        crossing = [a for a in atoms if "страница 2" in a["content"]]
        self.assertTrue(crossing, "нет атома на стыке")
        self.assertEqual(crossing[0]["page"], 1, [a["page"] for a in crossing])
        after = atoms[atoms.index(crossing[0]) + 1:]
        self.assertTrue(after)
        self.assertTrue(all(a["page"] == 2 for a in after), [a["page"] for a in after])


if __name__ == "__main__":
    unittest.main()