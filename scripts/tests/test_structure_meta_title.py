"""Метаданные из титула первой страницы (КоАП, ГОСТ, баннер)."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from import_document import normalize_text
from structure import DocImportOptions, extract_document_meta, prepare_for_import


class MetaTitleBlockTests(unittest.TestCase):
    def test_koap_two_line_title_effective_date_without_raw(self):
        raw = (
            "Кодекс Российской Федерации об административных правонарушениях "
            "от 30.12.2001 N 195-ФЗ\n"
            "(ред. от 01.03.2024)\n\n"
            "Глава 1. Общие положения\n\n"
            "Статья 1.1. Текст статьи достаточной длины для quality gate filter."
        )
        md = normalize_text(raw)
        _, ctx, _ = prepare_for_import(
            md,
            DocImportOptions(doc_kind="code", source_title="koap.pdf"),
        )
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.effective_date, "2024-03-01")
        self.assertEqual(ctx.law, "195-ФЗ")

    def test_gost_designation_from_first_page(self):
        raw = (
            "ГОСТ Р 55724-2013\n"
            "НАЦИОНАЛЬНЫЙ СТАНДАРТ\n\n"
            "1 Область применения\n"
            "Текст раздела один достаточной длины для quality gate filter test."
        )
        md = normalize_text(raw)
        _, ctx, _ = prepare_for_import(
            md,
            DocImportOptions(doc_kind="gost", source_title="gost55724.pdf"),
        )
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.standard, "ГОСТ Р 55724-2013")

    def test_law_after_midpage_banner(self):
        title = (
            "Гражданский кодекс Российской Федерации (часть вторая) "
            "от 26.01.1996 N 14-ФЗ (ред. от 01.03.2024)\n\n"
        )
        raw = (
            title
            + "Статья 474. Качество\n\n"
            "1. Начало пункта один без точки в конце фразы\n\n"
            "<!-- страница 2 -->\n\n"
            "Дата сохранения: 23.10.2026\n\n"
            "окончание пункта один достаточной длины для quality gate filter test.\n\n"
            "2. Пункт два достаточной длины для quality gate filter test case."
        )
        md = normalize_text(raw)
        _, ctx, _ = prepare_for_import(
            md,
            DocImportOptions(doc_kind="code", source_title="ban_cont.pdf"),
        )
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.law, "14-ФЗ")
        self.assertEqual(ctx.effective_date, "2024-03-01")
        red, eff, law, std, _ = extract_document_meta(
            md, DocImportOptions(source_title="ban_cont.pdf")
        )
        self.assertEqual(eff, "2024-03-01")
        self.assertEqual(law, "14-ФЗ")
        self.assertIsNone(std)


if __name__ == "__main__":
    unittest.main()
