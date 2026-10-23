"""Единая матрица регрессий: B1–B8, wraps, R1–R6, N1–N3, P1–P4 (positive recall)."""
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

AtomKey = tuple[str | None, str | None, str | None]


def _pipeline(
    lines: list[str],
    *,
    doc_kind: str = "code",
    title: str = "case.pdf",
    chunk_min: int = 30,
    md_text: str | None = None,
):
    if md_text is not None:
        md = normalize_text(md_text)
    else:
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


def _structure_keys(atoms: list) -> list[AtomKey]:
    out: list[AtomKey] = []
    for a in atoms:
        m = a.get("structure_meta") or {}
        pt = m.get("point")
        path = m.get("section_path") or []
        if not pt and path:
            pt = path[-1]
        if not m.get("article") and not path and not pt:
            continue
        out.append((m.get("article"), pt, m.get("subpoint")))
    return out


def _chk_gost_no_section_46(_ctx, atoms):
    assert not any(
        (a.get("structure_meta") or {}).get("section_path") == ["46"] for a in atoms
    )


def _chk_q4_no_121_points(_ctx, atoms):
    assert not any(
        (a.get("structure_meta") or {}).get("article") == "12.1"
        and (a.get("structure_meta") or {}).get("point") in ("2", "3")
        for a in atoms
    )


def _chk_n1_no_cascade(_ctx, atoms):
    assert not any(
        (a.get("structure_meta") or {}).get("article") == "12"
        and (a.get("structure_meta") or {}).get("point") in ("2", "3")
        for a in atoms
    )


def _assert_structure(atoms: list, expected: list[AtomKey], *, case_id: str) -> None:
    got = _structure_keys(atoms)
    assert got == expected, f"{case_id}: structure {got!r} != {expected!r}"


@dataclass(frozen=True)
class RulesCase:
    case_id: str
    lines: list[str]
    doc_kind: str
    title: str
    expected: list[AtomKey] | None
    extra: Callable[[object | None, list], None] | None = None
    md_text: str | None = None


CASES: list[RulesCase] = [
    RulesCase(
        "P1_point1_after_heading",
        [
            "Статья 474. Проверка качества товара",
            "1. Проверка проводится достаточной длины для quality gate filter.",
            "2. Иное положение также достаточной длины для quality gate.",
            "3. Третий пункт статьи четырёхсот семидесяти четырёх для gate.",
        ],
        "code",
        "p1.pdf",
        [("474", "1", None), ("474", "2", None), ("474", "3", None)],
    ),
    RulesCase(
        "R1_gk2020",
        [
            "ГК РФ ч. 2 (ред. от 01.01.2024)",
            "Статья 474. Общие положения",
            "1. Первый пункт статьи 474 достаточной длины для quality gate.",
            "2. Второй пункт статьи 474 также достаточно длинный для gate.",
            "Статья 475. Последствия",
            "1. Покупатель вправе потребовать уменьшения покупной цены.",
            "2. Покупатель вправе отказаться от исполнения договора и потребовать возврата.",
        ],
        "code",
        "gk2020.pdf",
        [
            ("474", "1", None),
            ("474", "2", None),
            ("475", "1", None),
            ("475", "2", None),
        ],
        lambda _c, atoms: _exact_match(
            [a for a in atoms if (a.get("structure_meta") or {}).get("point") == "2"
             and (a.get("structure_meta") or {}).get("article") == "475"][0]["content"],
            [a for a in atoms if (a.get("structure_meta") or {}).get("point") == "2"
             and (a.get("structure_meta") or {}).get("article") == "475"][0]["structure_meta"],
            parse_structured_query("п. 2 ст. 475"),
        ),
    ),
    RulesCase(
        "P2_toc_no_page_numbers",
        [
            "Статья 1. Введение",
            "Статья 2. Термины",
            "Статья 3. Общие положения",
            "Статья 1. Основные понятия",
            "1. Текст первой статьи основного текста достаточной длины для gate.",
            "Статья 2. Права",
            "1. Текст второй статьи основного текста достаточной длины для gate.",
        ],
        "code",
        "n_toc.pdf",
        [
            ("1", None, None),
            ("2", None, None),
            ("3", None, None),
            ("1", "1", None),
            ("2", "1", None),
        ],
    ),
    RulesCase(
        "R3_toc_with_dots",
        [
            "Оглавление",
            "Статья 1. Введение .............. 3",
            "Статья 2. Термины ............... 5",
            "Статья 3. Общие положения ....... 7",
            "Статья 1. Основные понятия",
            "1. Текст первой статьи основного текста достаточной длины для gate.",
        ],
        "code",
        "toc.pdf",
        [("2", None, None), ("3", None, None), ("1", "1", None)],
    ),
    RulesCase(
        "P3_fz_lowercase_subpoints",
        [
            "116-ФЗ О промышленной безопасности",
            "Статья 1. Общие положения",
            "1. Настоящий Федеральный закон регулирует достаточной длины для gate.",
            "2. Подлежат регистрации:",
            "1) в случае создания объекта достаточной длины для quality gate;",
            "2) в случае изменения объекта достаточной длины для quality gate.",
        ],
        "code",
        "fz_sub.pdf",
        [("1", "1", None), ("1", "2", None), ("1", "2", "1"), ("1", "2", "2")],
    ),
    RulesCase(
        "P3_real_subpoints_11_12",
        [
            "Статья 600. Замена товара",
            "1. Покупатель вправе потребовать замены товара достаточной длины.",
            "1.1. замены товара ненадлежащего качества достаточной длины;",
            "1.2. возмещения расходов на устранение недостатков достаточной длины.",
            "2. Срок исполнения обязательства достаточной длины для gate filter.",
        ],
        "code",
        "probe_list_pos.pdf",
        [
            ("600", "1", None),
            ("600", "1.1", None),
            ("600", "1.2", None),
            ("600", "2", None),
        ],
    ),
    RulesCase(
        "P4_point_after_date_sentence",
        [
            "Статья 474. Качество",
            "1. Норма вступает в силу с 01.09.2025.",
            "2. Второй пункт статьи достаточной длины для quality gate filter.",
        ],
        "code",
        "date_inline.pdf",
        [("474", "1", None), ("474", "2", None)],
    ),
    RulesCase(
        "P4_point_after_article_ref",
        [
            "Статья 474. Качество",
            "1. Предусмотрено статьей 12.",
            "2. Следующий пункт достаточной длины для quality gate filter test.",
        ],
        "code",
        "art12ref.pdf",
        [("474", "1", None), ("474", "2", None)],
    ),
    RulesCase(
        "B1_report_wrap",
        [
            "Отчёт по договору подряда для заказчика.",
            "Вводная часть описывает предмет работ достаточно подробно для quality gate.",
            "Оплата выполненных работ, как указано в договоре, регулирует",
            "статья 5. Порядок оплаты выполненных работ устанавливает календарный график.",
        ],
        "auto",
        "report_wrap.pdf",
        None,
    ),
    RulesCase(
        "B6_edge_p3",
        [
            "Статья 13. Судебный контроль",
            "1. Ненормативный акт может быть признан судом недействительным",
            "в соответствии с п. 3. Статья 12 настоящего Кодекса применяется также",
            "к актам органов местного самоуправления.",
        ],
        "code",
        "edge_p3.pdf",
        [("13", "1", None)],
    ),
    RulesCase(
        "wrap_475_lower",
        [
            "Статья 474. Качество",
            "1. Введение достаточной длины для прохождения quality gate filter.",
            "2. Если порядок не установлен, последствия передачи товара",
            "ненадлежащего качества определяет",
            "статья 475. Иные последствия могут быть предусмотрены договором.",
            "3. Обязательные требования к товару устанавливаются законом.",
            "Статья 475. Последствия",
            "1. Покупатель вправе потребовать уменьшения покупной цины.",
        ],
        "code",
        "gk474.pdf",
        [
            ("474", "1", None),
            ("474", "2", None),
            ("474", "3", None),
            ("475", "1", None),
        ],
    ),
    RulesCase(
        "N1_probe_mid",
        [
            "Статья 12. Способы защиты",
            "1. Текст двенадцатой статьи достаточной длины для quality gate.",
            "Статья 13. Общие положения",
            "1. Первый пункт тринадцатой статьи достаточной длины для gate.",
            "2. Порядок, который установлен в",
            "Статья 12. Способы защиты гражданских прав в полном объеме.",
            "3. Третий пункт тринадцатой статьи МАРКЕР13П3 достаточной длины.",
        ],
        "code",
        "probe_mid.pdf",
        [("12", "1", None), ("13", "1", None), ("13", "2", None), ("13", "3", None)],
        extra=_chk_n1_no_cascade,
    ),
    RulesCase(
        "N2_konst_bare",
        [
            "Конституция РФ",
            "Статья 1",
            "1. Текст первой статьи конституции достаточной длины для quality gate.",
            "Статья 2",
            "Человек, его права и свободы являются высшей ценностью достаточной длины.",
            "Статья 3",
            "1. Текст третьей статьи конституции достаточной длины для quality gate.",
        ],
        "code",
        "real_konst.pdf",
        [("1", "1", None), ("2", None, None), ("3", "1", None)],
    ),
    RulesCase(
        "N3_point_11_wrap",
        [
            "Статья 600. Сроки",
            "1. Первый пункт шестисотой статьи достаточной длины для quality gate.",
            "2. Срок исполнения обязательства, указанный в пункте",
            "1.1. настоящей статьи, составляет два года и достаточной длины.",
        ],
        "code",
        "probe_list.pdf",
        [("600", "1", None), ("600", "2", None)],
    ),
    RulesCase(
        "N3_wrap_475_point",
        [
            "Статья 474. Качество",
            "1. Введение достаточной длины для прохождения quality gate filter.",
            "2. Если порядок не установлен, последствия определяет статья",
            "475. Покупатель вправе потребовать уменьшения покупной цены.",
        ],
        "code",
        "wrap475.pdf",
        [("474", "1", None), ("474", "2", None)],
    ),
    RulesCase(
        "R5_gost_poryadok",
        [
            "ГОСТ Р 56542-2019",
            "4 Порядок",
            "4.1 Контроль проводят по утверждённой методике достаточной длины.",
        ],
        "gost",
        "gost_ref46.pdf",
        [(None, "4", None), (None, "4.1", None)],
    ),
    RulesCase(
        "Q1_heading_wrap",
        [
            "Статья 456. Обязанности продавца по передаче товаров,",
            "относящихся к товару",
            "1. Продавец обязан передать покупателю товар достаточной длины для gate.",
            "2. Второй пункт статьи четыреста пятьдесят шесть для quality gate.",
        ],
        "code",
        "c_heading_wrap.pdf",
        [("456", "1", None), ("456", "2", None)],
    ),
    RulesCase(
        "Q2_redline_paren",
        [
            "Статья 459. Ответственность",
            "1. Первый пункт статьи МАРКЕРРЛ1 достаточной длины для quality gate.",
            "(в ред. Федерального закона от 26.11.2001 N 147-ФЗ)",
            "2. Второй пункт статьи МАРКЕРРЛ2 достаточной длины для quality gate.",
            "(п. 2 в ред. Федерального закона от 01.01.2020 N 1-ФЗ)",
            "3. Третий пункт статьи МАРКЕРРЛ3 достаточной длины для quality gate.",
        ],
        "code",
        "c_redline.pdf",
        [("459", "1", None), ("459", "2", None), ("459", "3", None)],
    ),
    RulesCase(
        "Q3_page_glued_point",
        [
            "Статья 461. Передача",
            "1. Первый пункт статьи достаточной длины для quality gate filter test.",
            "2. Второй пункт с маркером МАРКЕРПЕ2 достаточной длины для gate. 1",
        ],
        "code",
        "c_pageend.pdf",
        [("461", "1", None), ("461", "2", None)],
    ),
    RulesCase(
        "Q3_mid_article_reject",
        [
            "Статья 12.4. Основная",
            "1. Текст статьи двенадцать четыре достаточной длины для quality gate.",
            "2. Ссылка на Статья 12.20. Устаревшая норма в середине текста достаточной длины.",
            "Статья 12.5. Следующая",
            "1. Текст статьи двенадцать пять достаточной длины для quality gate filter.",
            "Статья 12.6. Ещё",
            "1. Текст статьи двенадцать шесть достаточной длины для quality gate filter.",
        ],
        "code",
        "c_chain_hi.pdf",
        [("12.4", "1", None), ("12.4", "2", None), ("12.5", "1", None), ("12.6", "1", None)],
    ),
    RulesCase(
        "Q4_repealed_chain",
        [
            "Статья 12.1. Действующая",
            "1. Текст двенадцать один достаточной длины для quality gate filter.",
            "Статья 12.2. Утратила силу.",
            "Статья 12.3. Утратила силу.",
            "Статья 12.4. Управление",
            "1. Первый пункт двенадцать четыре достаточной длины для quality gate.",
            "2. Второй пункт МАРКЕР124П2 достаточной длины для quality gate filter.",
            "3. Третий пункт МАРКЕР124П3 достаточной длины для quality gate filter.",
        ],
        "code",
        "c_chain.pdf",
        [
            ("12.1", "1", None),
            ("12.2", None, None),
            ("12.3", None, None),
            ("12.4", "1", None),
            ("12.4", "2", None),
            ("12.4", "3", None),
        ],
        extra=_chk_q4_no_121_points,
    ),
    RulesCase(
        "Q2_toc_single_chapter",
        [
            "Глава 1. Общие положения",
            "Статья 1. Введение",
            "Глава 2. Права",
            "Статья 1. Основные понятия",
            "1. Текст первой статьи второй главы достаточной длины для gate.",
            "Статья 2. Права граждан",
            "1. Текст второй статьи достаточной длины для quality gate filter.",
        ],
        "code",
        "toc_single.pdf",
        [("1", "1", None), ("2", "1", None)],
    ),
    RulesCase(
        "B5_gk_paragraph_section",
        [
            "Статья 454. Продажа имущества",
            "1. Пункт четыре пять четыре первый достаточной длины для quality gate filter.",
            "2. Пункт четыре пять четыре второй достаточной длины для quality gate filter.",
            "§ 2. Розничная купля-продажа",
            "Статья 492. Договор розничной купли-продажи",
            "1. Пункт четыре девять два первый достаточной длины для quality gate filter.",
            "2. Пункт четыре девять два второй достаточной длины для quality gate filter.",
        ],
        "code",
        "q_para.pdf",
        [
            ("454", "1", None),
            ("454", "2", None),
            ("492", "1", None),
            ("492", "2", None),
        ],
    ),
    RulesCase(
        "B5_consultant_header_page",
        [],
        "code",
        "q_hdr_date.pdf",
        [
            ("474", "1", None),
            ("475", "1", None),
            ("475", "2", None),
            ("476", "1", None),
        ],
        md_text=(
            "<!-- страница 1 -->\n\n"
            "Статья 474. Качество товара\n\n"
            "1. Первый пункт четыре семь четыре достаточной длины для quality gate filter.\n\n"
            "<!-- страница 2 -->\n\n"
            "Документ предоставлен КонсультантПлюс Дата сохранения: 23.10.2026\n\n"
            "Статья 475. Недостатки товара\n\n"
            "1. Пункт четыре семь пять первый достаточной длины для quality gate filter.\n\n"
            "2. Пункт четыре семь пять второй достаточной длины для quality gate filter.\n\n"
            "Статья 476. Последствия\n\n"
            "1. Пункт четыре семь шесть первый достаточной длины для quality gate filter."
        ),
    ),
    RulesCase(
        "B5_toc_chapter_single_article",
        [
            "Статья 1. Введение .............. 3",
            "Статья 2. Термины ............... 5",
            "Статья 3. Общие положения ....... 7",
            "Глава II. Заключительные положения",
            "Статья 4. Вступление в силу ....... 9",
            "Текст преамбулы основного текста достаточной длины для quality gate filter.",
            "Статья 1. Основные понятия",
            "1. Текст первой статьи тела достаточной длины для quality gate filter.",
            "Статья 2. Права",
            "1. Текст второй статьи тела достаточной длины для quality gate filter.",
            "Статья 3. Обязанности",
            "1. Текст третьей статьи тела достаточной длины для quality gate filter.",
        ],
        "code",
        "q_toc_ch1.pdf",
        [
            ("2", None, None),
            ("3", None, None),
            ("4", None, None),
            ("1", "1", None),
            ("2", "1", None),
            ("3", "1", None),
        ],
    ),
    RulesCase(
        "B5_toc_repealed_tail",
        [
            "Статья 1. Раздел первый ........... 1",
            "Статья 2. Раздел второй ........... 2",
            "Статья 3.1. Утратила силу. ....... 3",
            "Статья 1. Тело первой",
            "1. Текст тела статьи один достаточной длины для quality gate filter.",
            "Статья 2. Тело второй",
            "1. Текст тела статьи два достаточной длины для quality gate filter.",
            "Статья 3. Тело третьей",
            "1. Текст тела статьи три достаточной длины для quality gate filter.",
        ],
        "code",
        "q_toc_rep.pdf",
        [
            ("2", None, None),
            ("3.1", None, None),
            ("1", "1", None),
            ("2", "1", None),
            ("3", "1", None),
        ],
    ),
    RulesCase(
        "B5_banner_mid_paragraph_brand",
        [],
        "code",
        "ban_cont_brand.pdf",
        [("474", "1", None), ("474", "2", None)],
        md_text=(
            "<!-- страница 1 -->\n\n"
            "Статья 474. Качество\n\n"
            "1. Первый пункт статьи четыре семь четыре начало предложения\n\n"
            "<!-- страница 2 -->\n\n"
            "КонсультантПлюс надежная правовая поддержка www.consultant.ru\n\n"
            "продолжение предложения первого пункта достаточной длины для quality gate filter.\n\n"
            "2. Второй пункт статьи четыре семь четыре достаточной длины для quality gate filter."
        ),
    ),
    RulesCase(
        "B5_banner_mid_paragraph_date",
        [],
        "code",
        "ban_cont_date.pdf",
        [("474", "1", None), ("474", "2", None)],
        md_text=(
            "<!-- страница 1 -->\n\n"
            "Статья 474. Качество\n\n"
            "1. Начало пункта один статьи четыре семь четыре без точки\n\n"
            "<!-- страница 2 -->\n\n"
            "Дата сохранения: 23.10.2026\n\n"
            "окончание пункта один достаточной длины для quality gate filter.\n\n"
            "2. Пункт два статьи четыре семь четыре достаточной длины для quality gate filter."
        ),
    ),
    RulesCase(
        "B5_toc_short2_redline",
        [
            "116-ФЗ О промышленной безопасности",
            "Статья 1. Основные понятия",
            "(в ред. Федерального закона от 04.03.2013 N 22-ФЗ)",
            "Статья 2. Опасные производственные объекты",
            "(в ред. Федерального закона от 04.03.2013 N 22-ФЗ)",
            "Статья 3. Требования промышленной безопасности",
            "Текст преамбулы достаточной длины для quality gate filter test.",
            "Статья 1. Основные понятия",
            "1. Текст первой статьи тела достаточной длины для quality gate filter.",
            "Статья 2. Опасные производственные объекты",
            "1. Текст второй статьи тела достаточной длины для quality gate filter.",
            "Статья 3. Требования промышленной безопасности",
            "1. Текст третьей статьи тела достаточной длины для quality gate filter.",
        ],
        "code",
        "q_toc_short2.pdf",
        [
            ("1", None, None),
            ("2", None, None),
            ("3", None, None),
            ("1", "1", None),
            ("2", "1", None),
            ("3", "1", None),
        ],
    ),
    RulesCase(
        "B5_koap_numend",
        [
            "КоАП РФ",
            "Статья 12.10. Нарушение правил движения через железнодорожные пути",
            "1. Пересечение железнодорожного пути влечет штраф в размере одной тысячи рублей",
            "2. Нарушение правил проезда через железнодорожный переезд влечет штраф",
            "Статья 12.11. Нарушение правил движения по автомагистрали",
            "1. Движение по автомагистрали на транспортном средстве достаточной длины для gate.",
        ],
        "code",
        "c_numend.pdf",
        [("12.10", "1", None), ("12.10", "2", None), ("12.11", "1", None)],
    ),
    RulesCase(
        "B5_toc_single_dotted_line",
        [
            "Статья 1. Основные понятия ........ 3",
            "Статья 1. Основные понятия",
            "1. Текст первой статьи тела достаточной длины для quality gate filter.",
            "Статья 2. Права граждан",
            "1. Текст второй статьи достаточной длины для quality gate filter.",
        ],
        "code",
        "toc_single_dot.pdf",
        [("1", "1", None), ("2", "1", None)],
    ),
    RulesCase(
        "Q_gost_ref46_no_46",
        [
            "ГОСТ Р 56542-2019",
            "1 Область применения",
            "Настоящий стандарт применяется в соответствии со статьей",
            "46 Федерального закона о техническом регулировании и достаточным текстом.",
            "4 Порядок",
            "4.1 Контроль проводят по утверждённой методике достаточной длины.",
        ],
        "gost",
        "gost_ref46_wrap.pdf",
        [(None, "1", None), (None, "4", None), (None, "4.1", None)],
        extra=_chk_gost_no_section_46,
    ),
    RulesCase(
        "P_gap_koap691_610",
        [
            "КоАП РФ",
            "Статья 6.9.1. Вовлечение в преступную деятельность",
            "1. Текст статьи шесть девять один достаточной длины для quality gate filter.",
            "Статья 6.10. Вовлечение в совершение преступления",
            "1. Текст статьи шесть десять достаточной длины для quality gate filter test.",
            "Статья 6.11. Занятие высшего положения",
            "1. Текст статьи шесть одиннадцать достаточной длины для quality gate filter.",
        ],
        "code",
        "gap_koap691.pdf",
        [
            ("6.9.1", "1", None),
            ("6.10", "1", None),
            ("6.11", "1", None),
        ],
    ),
    RulesCase(
        "P_gap_repealed_range",
        [
            "ЗК РФ",
            "Статья 7. Общие положения",
            "1. Текст статьи семь достаточной длины для quality gate filter test case.",
            "Статьи 8 - 14. Утратили силу",
            "Статья 15. Права собственника",
            "1. Текст статьи пятнадцать достаточной длины для quality gate filter test.",
        ],
        "code",
        "gap_rep_range.pdf",
        [("7", "1", None), ("15", "1", None)],
    ),
    RulesCase(
        "P_gap_repealed_list",
        [
            "ЗК РФ",
            "Статья 27. Предыдущая",
            "1. Текст статьи двадцать семь достаточной длины для quality gate filter test.",
            "Статья 28, статья 29, статья 30, статья 34. Утратили силу",
            "Статья 35. Следующая",
            "1. Текст статьи тридцать пять достаточной длины для quality gate filter test.",
        ],
        "code",
        "gap_rep_list.pdf",
        [("27", "1", None), ("35", "1", None)],
    ),
    RulesCase(
        "P_gap_inserted_191_197",
        [
            "НК РФ ч. 2",
            "Статья 19. Основная",
            "1. Текст статьи девятнадцать достаточной длины для quality gate filter test.",
            "Статья 19.1. Вставная первая",
            "1. Текст статьи девятнадцать один достаточной длины для quality gate filter test.",
            "Статья 19.7. Вставная седьмая",
            "1. Текст статьи девятнадцать семь достаточной длины для quality gate filter test.",
            "Статья 20. Следующая",
            "1. Текст статьи двадцать достаточной длины для quality gate filter test case.",
        ],
        "code",
        "gap_ins191.pdf",
        [
            ("19", "1", None),
            ("19.1", "1", None),
            ("19.7", "1", None),
            ("20", "1", None),
        ],
    ),
    RulesCase(
        "P_fwd_swallow_bare_recover",
        [
            "ГК РФ ч. 2",
            "Статья 474. Качество товара",
            "1. Проверка качества проводится в порядке, установленном договором, а также",
            "Статья 480",
            "настоящего Кодекса, если иное не предусмотрено договором, достаточной длины для gate.",
            "Статья 475. Недостатки товара",
            "1. Пункт четыре семь пять первый достаточной длины для quality gate filter test.",
            "Статья 476. Последствия",
            "1. Пункт четыре семь шесть первый достаточной длины для quality gate filter test.",
        ],
        "code",
        "fwd_swallow_bare.pdf",
        [
            ("474", "1", None),
            ("475", "1", None),
            ("476", "1", None),
        ],
    ),
    RulesCase(
        "P_fwd_swallow_noq_recover",
        [
            "ГК РФ ч. 2",
            "Статья 474. Качество товара",
            "1. Пункт 1 дополнить словами следующего содержания:",
            "Статья 480. Тара и упаковка товара определяются договором достаточной длины gate.",
            "Статья 475. Недостатки товара",
            "1. Пункт четыре семь пять первый достаточной длины для quality gate filter test.",
            "Статья 476. Последствия",
            "1. Пункт четыре семь шесть первый достаточной длины для quality gate filter test.",
        ],
        "code",
        "fwd_swallow_noq.pdf",
        [
            ("474", "1", None),
            ("475", "1", None),
            ("476", "1", None),
        ],
    ),
    RulesCase(
        "P_gap_titled_forward_jump",
        [
            "КоАП РФ",
            "Статья 12.5. Первый состав",
            "1. Текст статьи двенадцать пять достаточной длины для quality gate filter test.",
            "Статья 12.10. Другой состав",
            "1. Текст статьи двенадцать десять достаточной длины для quality gate filter test.",
        ],
        "code",
        "gap_titled_jump.pdf",
        [("12.5", "1", None), ("12.10", "1", None)],
    ),
]


class HeadingRulesMatrixTests(unittest.TestCase):
    def test_normalize_point1_after_heading(self):
        md = normalize_text(
            "Статья 474. Проверка качества товара\n"
            "1. Проверка проводится.\n2. Иное."
        )
        self.assertIn("\n\n1. Проверка", md)

    def test_matrix(self):
        for case in CASES:
            with self.subTest(case_id=case.case_id):
                if case.case_id == "B1_report_wrap":
                    md = normalize_text("\n".join(case.lines))
                    self.assertIsNone(detect_doc_kind(md, case.title, "auto"))
                ctx, atoms = _pipeline(
                    case.lines,
                    doc_kind=case.doc_kind,
                    title=case.title,
                    md_text=case.md_text,
                )
                if case.expected is not None:
                    _assert_structure(atoms, case.expected, case_id=case.case_id)
                if case.extra:
                    case.extra(ctx, atoms)

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
