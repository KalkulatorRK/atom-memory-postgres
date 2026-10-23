"""Регрессии полноты после 3395497 (R1–R6)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from import_document import normalize_text, pdf_to_text, quality_gate  # noqa: E402
from search_core import _exact_match, parse_structured_query  # noqa: E402
from structure import (  # noqa: E402
    DocImportOptions,
    _meta_source_text,
    detect_doc_kind,
    extract_document_meta,
    prepare_for_import,
    structure_split,
)
from tests.test_structure_e2e import _make_code_pdf  # noqa: E402


def _split(lines: list[str], *, kind: str = "code", title: str = "t.pdf"):
    with tempfile.TemporaryDirectory() as td:
        pdf = os.path.join(td, title)
        _make_code_pdf(pdf, lines)
        md = normalize_text(pdf_to_text(pdf))
        opts = DocImportOptions(doc_kind=kind, source_title=title)
        md2, ctx, _ = prepare_for_import(md, opts)
        assert ctx is not None
        return quality_gate(structure_split(md2, ctx, chunk_max=900, chunk_min=30))[0]


class RegressionR1Points(unittest.TestCase):
    def test_gk475_points_split(self):
        lines = [
            "ГК РФ ч. 2 (ред. от 01.01.2024)",
            "Статья 474. Общие положения",
            "1. Первый пункт статьи 474 достаточной длины для quality gate.",
            "2. Второй пункт статьи 474 также достаточно длинный для gate.",
            "Статья 475. Последствия",
            "1. Покупатель вправе потребовать уменьшения покупной цены.",
            "2. Покупатель вправе отказаться от исполнения договора и потребовать возврата.",
        ]
        atoms = _split(lines, title="gk2020.pdf")
        p475_2 = [
            a
            for a in atoms
            if a.get("structure_meta", {}).get("article") == "475"
            and a.get("structure_meta", {}).get("point") == "2"
        ]
        self.assertTrue(p475_2)
        sq = parse_structured_query("п. 2 ст. 475")
        self.assertTrue(_exact_match(p475_2[0]["content"], p475_2[0]["structure_meta"], sq))


class RegressionR2Koap(unittest.TestCase):
    def test_article_12_10_separate(self):
        lines = [
            "КоАП РФ",
            "Статья 12.8. Первая",
            "1. Текст статьи двенадцать восемь достаточной длины для прохождения gate.",
            "Статья 12.9. Вторая",
            "1. Текст статьи двенадцать девять достаточной длины для прохождения gate.",
            "Статья 12.10. Десятая",
            "1. Текст статьи двенадцать десять достаточной длины для gate filter.",
            "Статья 12.11. Одиннадцатая",
            "1. Текст одиннадцатой статьи достаточной длины для quality gate filter.",
        ]
        atoms = _split(lines, title="koap.pdf")
        nums = {a.get("structure_meta", {}).get("article") for a in atoms}
        self.assertIn("12.10", nums)
        self.assertIn("12.11", nums)


class RegressionR3Toc(unittest.TestCase):
    def test_body_after_toc(self):
        lines = [
            "Оглавление",
            "Статья 1. Введение .............. 3",
            "Статья 2. Термины ............... 5",
            "Статья 3. Общие положения ....... 7",
            "Статья 1. Основные понятия",
            "1. Текст первой статьи основного текста достаточной длины для gate.",
            "Статья 2. Права",
            "1. Текст второй статьи основного текста достаточной длины для gate.",
        ]
        atoms = _split(lines, title="toc.pdf")
        joined = " ".join(a["content"] for a in atoms)
        self.assertIn("Основные понятия", joined)
        self.assertIn("Права", joined)
        body1 = [
            a
            for a in atoms
            if a.get("structure_meta", {}).get("article") == "1"
            and "Основные понятия" in a["content"]
        ]
        self.assertTrue(body1)


class RegressionR4BareArticle(unittest.TestCase):
    def test_constitution_bare_heading(self):
        lines = [
            "Конституция РФ",
            "Статья 1",
            "1. Текст первой статьи конституции достаточной длины для quality gate.",
            "Статья 2",
            "1. Текст второй статьи конституции достаточной длины для quality gate.",
        ]
        md = normalize_text("\n".join(lines))
        self.assertEqual(detect_doc_kind(md, "konst.pdf", "auto"), "code")
        atoms = _split(lines, kind="auto", title="konst.pdf")
        self.assertGreaterEqual(len(atoms), 2)


class RegressionR5GostSectionK(unittest.TestCase):
    def test_poryadok_not_dangling(self):
        lines = [
            "ГОСТ Р 56542-2019",
            "4 Порядок",
            "4.1 Контроль проводят по утверждённой методике достаточной длины.",
            "4.2 Документирование результатов контроля также достаточно длинное.",
        ]
        atoms = _split(lines, kind="gost", title="gost_ref46.pdf")
        s41 = [
            a
            for a in atoms
            if a.get("structure_meta", {}).get("section_path") == ["4", "4.1"]
        ]
        self.assertTrue(s41)


class RegressionR6Dates(unittest.TestCase):
    def test_redaction_in_body_ignored(self):
        text = (
            "ГК РФ ч. 2\n\n"
            "Статья 474. Тест\n"
            "1. Пункт (пункт в ред. от 12.03.2014) достаточной длины для gate."
        )
        red, eff, *_ = extract_document_meta(text, DocImportOptions(source_title="d.pdf"))
        self.assertIsNone(eff)
        self.assertIsNone(red)

    def test_header_redaction_wins_over_body_effective(self):
        text = (
            "ГК РФ ч. 2 (ред. от 01.03.2024)\n\n"
            "Статья 474. Тест\n"
            "1. Норма вступает в силу с 01.09.2025 и достаточной длины для gate."
        )
        red, eff, *_ = extract_document_meta(text, DocImportOptions(source_title="d.pdf"))
        self.assertEqual(eff, "2024-03-01")
        self.assertIn("ред.", red or "")

    def test_wrapped_consultant_title_effective_date(self):
        raw = (
            "Гражданский кодекс Российской Федерации (часть первая)\n"
            "от 26.01.1996 N 14-ФЗ (ред. от\n"
            "01.03.2024)\n\n"
            "Статья 1. Общие положения\n"
            "1. Текст первой статьи достаточной длины для quality gate filter."
        )
        blob = _meta_source_text(raw, "gk2024.pdf")
        red, eff, law, *_ = extract_document_meta(
            blob, DocImportOptions(source_title="gk2024.pdf")
        )
        self.assertEqual(eff, "2024-03-01")
        self.assertIn("ред.", red or "")
        self.assertIn("14", law or "")

    def test_wrapped_title_after_normalize_keeps_effective_date(self):
        raw = (
            "Гражданский кодекс Российской Федерации (часть первая)\n"
            "от 26.01.1996 N 14-ФЗ (ред. от\n"
            "01.03.2024)\n\n"
            "Статья 1. Общие положения\n"
            "1. Текст первой статьи достаточной длины для quality gate filter."
        )
        md = normalize_text(raw)
        _, ctx, _ = prepare_for_import(
            md,
            DocImportOptions(doc_kind="code", source_title="gk2024.pdf"),
            meta_source=raw,
        )
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.effective_date, "2024-03-01")


if __name__ == "__main__":
    unittest.main()
