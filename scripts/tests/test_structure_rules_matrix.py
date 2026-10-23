"""Единая матрица регрессий: B1–B8, wraps, R1–R6, N1–N3."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from dataclasses import dataclass
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from import_document import normalize_text, pdf_to_text, quality_gate  # noqa: E402
from search_core import _exact_match, parse_structured_query  # noqa: E402
from structure import DocImportOptions, detect_doc_kind, extract_document_meta, prepare_for_import, structure_split  # noqa: E402
from tests.test_structure_e2e import _make_code_pdf  # noqa: E402


def _pipeline(
    lines: list[str],
    *,
    doc_kind: str = "code",
    title: str = "case.pdf",
    chunk_min: int = 30,
):
    with tempfile.TemporaryDirectory() as td:
        pdf = os.path.join(td, title)
        _make_code_pdf(pdf, lines)
        md = normalize_text(pdf_to_text(pdf))
        opts = DocImportOptions(doc_kind=doc_kind, source_title=title)
        md2, ctx, _ = prepare_for_import(md, opts)
        if not ctx:
            from import_document import smart_split

            atoms, _ = quality_gate(smart_split(md2))
            return None, atoms
        atoms, _ = quality_gate(
            structure_split(md2, ctx, chunk_max=900, chunk_min=chunk_min)
        )
        return ctx, atoms


@dataclass(frozen=True)
class RulesCase:
    case_id: str
    lines: list[str]
    doc_kind: str
    title: str
    check: Callable[[object | None, list], None]


def _chk_b1(_ctx, atoms):
    assert not any(a.get("structure_meta", {}).get("article") for a in atoms)


def _chk_b6(_ctx, atoms):
    assert not [a for a in atoms if a.get("structure_meta", {}).get("article") == "12"]


def _chk_wrap_475(_ctx, atoms):
    fake = [
        a
        for a in atoms
        if a.get("structure_meta", {}).get("article") == "475"
        and "Иные последствия" in a["content"]
        and "Покупатель" not in a["content"]
    ]
    assert not fake
    p2 = [
        a
        for a in atoms
        if a.get("structure_meta", {}).get("article") == "474"
        and a.get("structure_meta", {}).get("point") == "2"
    ]
    assert p2 and "статья 475. Иные" in p2[0]["content"]


def _chk_r1(_ctx, atoms):
    p = [
        a
        for a in atoms
        if a.get("structure_meta", {}).get("article") == "475"
        and a.get("structure_meta", {}).get("point") == "2"
    ]
    assert p
    sq = parse_structured_query("п. 2 ст. 475")
    assert _exact_match(p[0]["content"], p[0]["structure_meta"], sq)


def _chk_r2(_ctx, atoms):
    assert "12.10" in {a.get("structure_meta", {}).get("article") for a in atoms}


def _chk_r3(_ctx, atoms):
    assert any(
        a.get("structure_meta", {}).get("article") == "1" and "Основные понятия" in a["content"]
        for a in atoms
    )


def _chk_n1(_ctx, atoms):
    p3 = [
        a
        for a in atoms
        if a.get("structure_meta", {}).get("article") == "13"
        and a.get("structure_meta", {}).get("point") == "3"
    ]
    assert p3 and "МАРКЕР13П3" in p3[0]["content"]
    bad = [
        a
        for a in atoms
        if a.get("structure_meta", {}).get("article") == "12"
        and "МАРКЕР13П3" in a["content"]
    ]
    assert not bad


def _chk_n2(_ctx, atoms):
    assert any(
        a.get("structure_meta", {}).get("article") == "2" and "Человек" in a["content"]
        for a in atoms
    )


def _chk_n3_list(_ctx, atoms):
    assert not any(a.get("structure_meta", {}).get("point") == "1.1" for a in atoms)
    p2 = [
        a
        for a in atoms
        if a.get("structure_meta", {}).get("article") == "600"
        and a.get("structure_meta", {}).get("point") == "2"
    ]
    assert p2 and "1.1. настоящей" in p2[0]["content"]


def _chk_n3_475(_ctx, atoms):
    assert not any(a.get("structure_meta", {}).get("point") == "475" for a in atoms)


def _chk_r5(_ctx, atoms):
    assert any(
        a.get("structure_meta", {}).get("section_path") == ["4", "4.1"] for a in atoms
    )


CASES: list[RulesCase] = [
    RulesCase("B1_report_wrap", [
        "Отчёт по договору подряда для заказчика.",
        "Вводная часть описывает предмет работ достаточно подробно для quality gate.",
        "Оплата выполненных работ, как указано в договоре, регулирует",
        "статья 5. Порядок оплаты выполненных работ устанавливает календарный график.",
    ], "auto", "report_wrap.pdf", _chk_b1),
    RulesCase("B6_edge_p3", [
        "Статья 13. Судебный контроль",
        "1. Ненормативный акт может быть признан судом недействительным",
        "в соответствии с п. 3. Статья 12 настоящего Кодекса применяется также",
        "к актам органов местного самоуправления.",
    ], "code", "edge_p3.pdf", _chk_b6),
    RulesCase("wrap_475_lower", [
        "Статья 474. Качество",
        "1. Введение достаточной длины для прохождения quality gate filter.",
        "2. Если порядок не установлен, последствия передачи товара",
        "ненадлежащего качества определяет",
        "статья 475. Иные последствия могут быть предусмотрены договором.",
        "3. Обязательные требования к товару устанавливаются законом.",
        "Статья 475. Последствия",
        "1. Покупатель вправе потребовать уменьшения покупной цены.",
    ], "code", "gk474.pdf", _chk_wrap_475),
    RulesCase("R1_gk475_search", [
        "ГК РФ ч. 2 (ред. от 01.01.2024)",
        "Статья 474. Общие положения",
        "1. Первый пункт статьи 474 достаточной длины для quality gate.",
        "2. Второй пункт статьи 474 также достаточно длинный для gate.",
        "Статья 475. Последствия",
        "1. Покупатель вправе потребовать уменьшения покупной цены.",
        "2. Покупатель вправе отказаться от исполнения договора и потребовать возврата.",
    ], "code", "gk2020.pdf", _chk_r1),
    RulesCase("R2_koap_12_10", [
        "КоАП РФ",
        "Статья 12.9. Девятая",
        "1. Текст статьи двенадцать девять достаточной длины для gate.",
        "Статья 12.10. Десятая",
        "1. Текст статьи двенадцать десять достаточной длины для gate filter.",
    ], "code", "koap.pdf", _chk_r2),
    RulesCase("R3_toc_body", [
        "Оглавление",
        "Статья 1. Введение .............. 3",
        "Статья 2. Термины ............... 5",
        "Статья 3. Общие положения ....... 7",
        "Статья 1. Основные понятия",
        "1. Текст первой статьи основного текста достаточной длины для gate.",
    ], "code", "toc.pdf", _chk_r3),
    RulesCase("N1_probe_mid", [
        "Статья 12. Способы защиты",
        "1. Текст двенадцатой статьи достаточной длины для quality gate.",
        "Статья 13. Общие положения",
        "1. Первый пункт тринадцатой статьи достаточной длины для gate.",
        "2. Порядок, который установлен в",
        "Статья 12. Способы защиты гражданских прав в полном объеме.",
        "3. Третий пункт тринадцатой статьи МАРКЕР13П3 достаточной длины.",
    ], "code", "probe_mid.pdf", _chk_n1),
    RulesCase("N2_konst_bare", [
        "Конституция РФ",
        "Статья 1",
        "1. Текст первой статьи конституции достаточной длины для quality gate.",
        "Статья 2",
        "Человек, его права и свободы являются высшей ценностью достаточной длины.",
        "Статья 3",
        "1. Текст третьей статьи конституции достаточной длины для quality gate.",
    ], "code", "real_konst.pdf", _chk_n2),
    RulesCase("N3_point_11_wrap", [
        "Статья 600. Сроки",
        "1. Первый пункт шестисотой статьи достаточной длины для quality gate.",
        "2. Срок исполнения обязательства, указанный в пункте",
        "1.1. настоящей статьи, составляет два года и достаточной длины.",
    ], "code", "probe_list.pdf", _chk_n3_list),
    RulesCase("N3_wrap_475_point", [
        "Статья 474. Качество",
        "1. Введение достаточной длины для прохождения quality gate filter.",
        "2. Если порядок не установлен, последствия определяет статья",
        "475. Покупатель вправе потребовать уменьшения покупной цены.",
    ], "code", "wrap475.pdf", _chk_n3_475),
    RulesCase("R5_gost_poryadok", [
        "ГОСТ Р 56542-2019",
        "4 Порядок",
        "4.1 Контроль проводят по утверждённой методике достаточной длины.",
    ], "gost", "gost_ref46.pdf", _chk_r5),
]


class HeadingRulesMatrixTests(unittest.TestCase):
    def test_matrix(self):
        for case in CASES:
            with self.subTest(case_id=case.case_id):
                if case.case_id == "B1_report_wrap":
                    md = normalize_text("\n".join(case.lines))
                    self.assertIsNone(detect_doc_kind(md, case.title, "auto"))
                ctx, atoms = _pipeline(
                    case.lines, doc_kind=case.doc_kind, title=case.title
                )
                case.check(ctx, atoms)

    def test_r6_header_dates(self):
        text = (
            "ГК РФ ч. 2\n\nСтатья 474. Тест\n"
            "1. Пункт (пункт в ред. от 12.03.2014) достаточной длины."
        )
        red, eff, *_ = extract_document_meta(
            text, DocImportOptions(source_title="d.pdf")
        )
        self.assertIsNone(eff)
        self.assertIsNone(red)


if __name__ == "__main__":
    unittest.main()
