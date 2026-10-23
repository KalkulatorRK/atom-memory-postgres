"""PDF переносы строк: ложные статьи/разделы (B6/B1)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from import_document import normalize_text, pdf_to_text, quality_gate, smart_split  # noqa: E402
from search_core import _exact_match, parse_structured_query  # noqa: E402
from structure import DocImportOptions, detect_doc_kind, prepare_for_import, structure_split  # noqa: E402
from tests.test_structure_e2e import _make_code_pdf  # noqa: E402


def _pipeline(pdf_lines: list[str], *, doc_kind: str = "auto", title: str = "doc.pdf"):
    with tempfile.TemporaryDirectory() as td:
        pdf = os.path.join(td, title)
        _make_code_pdf(pdf, pdf_lines)
        md = normalize_text(pdf_to_text(pdf))
        opts = DocImportOptions(doc_kind=doc_kind, source_title=title)
        md2, ctx, _ = prepare_for_import(md, opts)
        if not ctx:
            atoms, _ = quality_gate(smart_split(md2))
            return None, atoms
        atoms, _ = quality_gate(
            structure_split(md2, ctx, chunk_max=900, chunk_min=40)
        )
        return ctx, atoms


class PdfWrapRegressionTests(unittest.TestCase):
    def test_p3_dot_not_article_12_split(self):
        lines = [
            "Статья 13. Судебный контроль",
            "1. Ненормативный акт может быть признан судом недействительным",
            "в соответствии с п. 3. Статья 12 настоящего Кодекса применяется также",
            "к актам органов местного самоуправления.",
        ]
        ctx, atoms = _pipeline(lines, doc_kind="code", title="gk_ch1.pdf")
        self.assertEqual(ctx.doc_kind, "code")
        fake12 = [
            a
            for a in atoms
            if a.get("structure_meta", {}).get("article") == "12"
        ]
        self.assertFalse(fake12)
        joined = " ".join(a["content"] for a in atoms)
        self.assertIn("п. 3.", joined)
        self.assertIn("Статья 12 настоящего", joined)
        sq = parse_structured_query("ст. 12")
        for a in atoms:
            if "настоящего Кодекса применяется" in a["content"]:
                self.assertFalse(
                    _exact_match(a["content"], a.get("structure_meta") or {}, sq)
                )

    def test_wrap_lowercase_475_not_heading(self):
        lines = [
            "Статья 474. Качество",
            "1. Введение.",
            "2. Если порядок не установлен, последствия передачи товара",
            "ненадлежащего качества определяет",
            "статья 475. Иные последствия могут быть предусмотрены договором.",
            "3. Обязательные требования к товару устанавливаются законом.",
            "Статья 475. Последствия",
            "1. Покупатель вправе потребовать уменьшения покупной цены.",
        ]
        ctx, atoms = _pipeline(lines, doc_kind="code", title="gk474.pdf")
        wrap_fake = [
            a
            for a in atoms
            if a.get("structure_meta", {}).get("article") == "475"
            and "Иные последствия" in a["content"]
            and "Покупатель" not in a["content"]
        ]
        self.assertFalse(wrap_fake)
        in474 = [
            a
            for a in atoms
            if a.get("structure_meta", {}).get("article") == "474"
            and "статья 475. Иные" in a["content"]
            and "Обязательные требования" in a["content"]
        ]
        self.assertTrue(in474)

    def test_gost_wrap_no_article_metadata(self):
        lines = [
            "ГОСТ 12345-2020 Трубы",
            "2 Требования",
            "2.1 Качество",
            "Требования к качеству определяет",
            "статья 5. Остальные требования устанавливает заказчик.",
            "2.2 Маркировка",
            "Маркировка должна быть читаемой и достаточно длинной для теста.",
        ]
        ctx, atoms = _pipeline(lines, doc_kind="gost", title="gost_wrap.pdf")
        self.assertEqual(ctx.doc_kind, "gost")
        with_article = [a for a in atoms if a.get("structure_meta", {}).get("article")]
        self.assertFalse(with_article)
        s22 = [
            a
            for a in atoms
            if a.get("structure_meta", {}).get("section_path") == ["2", "2.2"]
        ]
        self.assertTrue(s22)

    def test_report_wrap_not_code_kind(self):
        lines = [
            "Отчёт по договору подряда для заказчика.",
            "Вводная часть описывает предмет работ достаточно подробно для quality gate.",
            "Оплата выполненных работ, как указано в договоре, регулирует",
            "статья 5. Порядок оплаты выполненных работ устанавливает календарный график.",
            "Сроки приёмки результата и претензионный порядок описывает",
            "статья 7. Нарушений сроков приемки допускается не более двух случаев.",
        ]
        md = normalize_text("\n".join(lines))
        kind = detect_doc_kind(md, "report_wrap.pdf", "auto")
        self.assertIsNone(kind)
        ctx, atoms = _pipeline(lines, doc_kind="auto", title="report_wrap.pdf")
        self.assertIsNone(ctx)
        arts = [a.get("structure_meta", {}).get("article") for a in atoms if isinstance(a, dict)]
        self.assertFalse(any(arts))

    def test_gost_fz_wrap_not_section_46(self):
        lines = [
            "ГОСТ 12345-2020",
            "1 Область применения",
            "Настоящий стандарт применяется в соответствии со статьей",
            "46 Федерального закона о техническом регулировании и достаточным текстом.",
            "1.1 Общие положения",
            "Требования распространяются на все виды продукции в рамках стандарта.",
        ]
        ctx, atoms = _pipeline(lines, doc_kind="gost", title="gost_fz.pdf")
        bad = [
            a
            for a in atoms
            if a.get("structure_meta", {}).get("section_path") == ["46"]
        ]
        self.assertFalse(bad)
        sq = parse_structured_query("п. 46")
        for a in atoms:
            if "Федерального закона" in a["content"]:
                self.assertFalse(
                    _exact_match(a["content"], a.get("structure_meta") or {}, sq)
                )


if __name__ == "__main__":
    unittest.main()
