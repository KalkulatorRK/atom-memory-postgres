"""E2E: PDF → normalize_text → structure_split (как import_document)."""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from import_document import normalize_text, pdf_to_text, quality_gate  # noqa: E402
from structure import DocImportOptions, detect_doc_kind, prepare_for_import, structure_split  # noqa: E402


_DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _make_code_pdf(path: str, lines: list[str]) -> None:
    import fitz

    if not os.path.isfile(_DEJAVU):
        raise unittest.SkipTest(f"Cyrillic font not found: {_DEJAVU}")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="DejaVuSans", fontfile=_DEJAVU)
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=11, fontname="DejaVuSans")
        y += 16
        if y > 750:
            page = doc.new_page()
            page.insert_font(fontname="DejaVuSans", fontfile=_DEJAVU)
            y = 72
            page.insert_text((72, y), line, fontsize=11, fontname="DejaVuSans")
            y += 16
    doc.save(path)
    doc.close()


class StructureE2ETests(unittest.TestCase):
    def test_pdf_pipeline_preserves_all_articles(self):
        lines = [
            "ГК РФ ч. 2 (ред. от 01.01.2024)",
            "Статья 12. Общие положения",
            "1. Первый пункт статьи двенадцать достаточной длины для quality gate.",
            "Статья 13. Следующая статья",
            "1. Текст статьи тринадцать также достаточно длинный для прохождения фильтра.",
            "Статья 14. Переход",
            "3) отказаться от исполнения договора в установленном законом порядке.",
            "Статья 15. Возмещение убытков",
            "1. Лицо вправе требовать полного возмещения убытков если это предусмотрено законом.",
        ]
        with tempfile.TemporaryDirectory() as td:
            pdf = os.path.join(td, "gk_part2.pdf")
            _make_code_pdf(pdf, lines)
            md = normalize_text(pdf_to_text(pdf))
            opts = DocImportOptions(doc_kind="code", source_title="ГК РФ ч. 2")
            md2, ctx, _ = prepare_for_import(md, opts)
            atoms, _ = quality_gate(
                structure_split(md2, ctx, chunk_max=500, chunk_min=50)
            )
        arts = {a.get("structure_meta", {}).get("article") for a in atoms}
        self.assertIn("12", arts)
        self.assertIn("13", arts)
        self.assertIn("14", arts)
        self.assertIn("15", arts)
        joined = " ".join(a["content"] for a in atoms)
        for token in ("двенадцать", "тринадцать", "Возмещение", "отказаться"):
            self.assertIn(token, joined)
        a15 = [a for a in atoms if a.get("structure_meta", {}).get("article") == "15"]
        self.assertTrue(a15)
        self.assertNotIn("14", a15[0]["content"][:40])
        src = " ".join(" ".join(lines).split())
        got = " ".join(" ".join(a["content"] for a in atoms).split())
        for word in re.findall(r"[\wа-яА-ЯёЁ]+", src):
            if len(word) > 4:
                self.assertIn(word, got, msg=f"missing token {word!r} from source")

    def test_casual_article_does_not_trigger_code(self):
        text = normalize_text(
            "Отчёт по договору.\nстатья 5 договора описывает сроки.\n"
            "статья 7 договора про оплату.\n" + ("Подробный текст раздела. " * 15)
        )
        kind = detect_doc_kind(text, "report.pdf", "auto")
        self.assertIsNone(kind)


if __name__ == "__main__":
    unittest.main()
