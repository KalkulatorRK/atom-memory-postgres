"""Структурная нарезка кодексов и нормативных документов (VS-14, VS-15)."""
from __future__ import annotations

import copy
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from structure_headings import (
    ArticleHeadingState,
    StructureLineState,
    accept_article_heading,
    accept_code_point_line,
    detect_lowercase_heading_style,
    is_consultant_running_header_prefix,
    is_paren_boundary_line,
    is_running_header_line,
    is_strict_code_chapter_heading,
    is_strict_code_paragraph_heading,
    is_strict_code_section_heading,
    is_strict_code_subsection_heading,
    is_strict_code_volume_heading,
    is_structure_heading_line,
    is_toc_heading_line,
    split_inline_article_segments,
    update_toc_state,
)

PAGE_MARK = re.compile(r"<!-- страница (\d+) -->")
COLONTITUL_LINE = re.compile(
    r"^(?:ГОСТ(?:\s*Р)?|СДАНК|СТО|ISO)\s*[-\w.]+\s*(?:С\.|стр\.)\s*\d+\s*$",
    re.IGNORECASE,
)
COLONTITUL_TAIL = re.compile(
    r"\s+(?:ГОСТ(?:\s*Р)?|СДАНК|СТО)\s*[-\w.]+\s*(?:С\.|стр\.)\s*\d+\s*$",
    re.IGNORECASE,
)
RE_ARTICLE = re.compile(
    r"^(?:Статья|СТАТЬЯ)\s+(\d+(?:\.\d+)?)(?:[.\s—–-]\s*(.*))?$"
)
RE_CHAPTER = re.compile(r"^Глава\s+(\d+(?:\.\d+)*)")
RE_PART = re.compile(
    r"^Часть\s+(?:первая|вторая|третья|четв[её]ртая|пят(?:ая|ая)|(\d+))",
    re.IGNORECASE,
)
RE_SECTION_CODE = re.compile(
    r"^(?:Раздел|РАЗДЕЛ|Подраздел|ПОДРАЗДЕЛ)\s+([IVX\d]+)",
    re.IGNORECASE,
)
RE_POINT = re.compile(r"^(\d+(?:\.\d+)*)\.\s+")
RE_SUBPOINT = re.compile(r"^(\d+)\)\s+")
RE_GOST_SECTION = re.compile(r"^(\d+(?:\.\d+){0,4})\s+(?=\S)")
RE_ANNEX = re.compile(
    r"^(?:Приложение|ПРИЛОЖЕНИЕ)\s+([А-ЯA-Z])(?:\s|\(|$)",
    re.IGNORECASE,
)
RE_REDACTION = re.compile(
    r"(?:ред\.?\s*от|редакция\s*от)\s*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    re.IGNORECASE,
)
RE_EFFECTIVE = re.compile(
    r"(?:в\s*силу\s*с|действует\s*с)\s*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    re.IGNORECASE,
)
RE_LAW = re.compile(
    r"\b((?:ГК|ГПК|АПК|УК|НК|ТК|ЖК|СК|БК)\s*РФ(?:\s*ч\.\s*\d+)?)\b",
    re.IGNORECASE,
)
RE_STANDARD_TITLE = re.compile(
    r"(?<![а-яёa-z])("
    r"(?:ГОСТ(?:\s*Р)?\s*[\d][\d.\w\-]*"
    r"|СДАНК[-\w]+"
    r"|(?-i:СТО)\s+(?:Газпром\s+[\d][-\d.]+|\d+[-\d.]+|[A-Za-zА-ЯЁ][\w\s-]*[\d][-\d.]*)"
    r"|ISO\s*[-\d][-\w]*)"
    r")(?=[\s,.;]|$)",
    re.IGNORECASE,
)
RE_LAW_FZ = re.compile(r"\b(\d{1,4}-ФЗ)\b", re.IGNORECASE)
RE_LAW_FULL = re.compile(
    r"(?i)\b((?:Гражданский|Уголовный|Трудовой|Налоговый|Кодекс)\s+[^\n]{0,80}?(?:\d{1,4}-ФЗ|РФ))"
)
RE_FZ_LINE = re.compile(r"^\d+\s+Федерального\s+зак", re.IGNORECASE)
RE_DANGLING_REF = re.compile(
    r"(?i)(?:\bстатьей|\bстатьи|\bстатью|\bсо|\bк)\s*$"
)
RE_DATE_LINE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}\b")
RE_ARTICLE_HEADING = re.compile(r"^(?:Статья|СТАТЬЯ)\s+(\d+(?:\.\d+)?)\b")
RE_ARTICLE_HEADING_CI = re.compile(
    r"^(?:Статья|СТАТЬЯ|статья)\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE
)
RE_CASUAL_ARTICLE = re.compile(r"(?:^|[\s,.;(])стать(?:я|и|ей|ю)\s+\d+")
RE_GOST_SECTION_STRICT = re.compile(
    r"^(\d+(?:\.\d+){0,4})\s+([A-ZА-ЯЁ«\"].*)"
)
RE_INTRO_DATE = re.compile(
    r"(?:Дата\s+введения|дата\s+введения)\s*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    re.IGNORECASE,
)
RE_INLINE_POINT_START = re.compile(r"\s(\d+\.\s+[A-ZА-ЯЁ«\"(])")

PART_WORDS = {
    "первая": "1",
    "вторая": "2",
    "третья": "3",
    "четвертая": "4",
    "четвёртая": "4",
    "пятая": "5",
}


@dataclass
class DocImportOptions:
    doc_kind: str = "auto"
    redaction: str | None = None
    effective_date: str | None = None
    source_title: str = ""


@dataclass
class StructureContext:
    doc_kind: str | None = None
    standard: str | None = None
    law: str | None = None
    chapter: str | None = None
    article: str | None = None
    article_title: str | None = None
    point: str | None = None
    subpoint: str | None = None
    section_path: list[str] = field(default_factory=list)
    annex: str | None = None
    redaction: str | None = None
    effective_date: str | None = None
    redaction_source: str | None = None
    page: int | None = None

    def metadata(self) -> dict[str, Any]:
        m: dict[str, Any] = {}
        if self.doc_kind:
            m["doc_kind"] = self.doc_kind
        if self.standard:
            m["standard"] = self.standard
        if self.law:
            m["law"] = self.law
        if self.chapter:
            m["chapter"] = self.chapter
        if self.article:
            m["article"] = self.article
        if self.article_title:
            m["article_title"] = self.article_title
        if self.point:
            m["point"] = self.point
        if self.subpoint:
            m["subpoint"] = self.subpoint
        if self.section_path:
            m["section_path"] = list(self.section_path)
        if self.annex:
            m["annex"] = self.annex
        if self.redaction:
            m["redaction"] = self.redaction
        if self.effective_date:
            m["effective_date"] = self.effective_date
        if self.redaction_source:
            m["redaction_source"] = self.redaction_source
        return m

    def boundary_key(self) -> tuple:
        if self.doc_kind == "code":
            return ("code", self.article, self.point, self.subpoint)
        if self.doc_kind in ("gost", "sdank"):
            return ("norm", tuple(self.section_path), self.annex)
        return ("plain",)

    def copy(self) -> StructureContext:
        return copy.deepcopy(self)


def parse_date_strict(raw: str | None) -> date | None:
    if not raw:
        return None
    s = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})$", s)
    if not m:
        return None
    d, mo, y = m.groups()
    yi = int(y)
    if len(y) == 2:
        yi = 1900 + yi if yi >= 70 else 2000 + yi
    try:
        return date(yi, int(mo), int(d))
    except ValueError:
        return None


def normalize_date(raw: str | None) -> str | None:
    d = parse_date_strict(raw)
    return d.isoformat() if d else None


def law_ilike_pattern(law: str | None) -> str | None:
    if not law:
        return None
    if "%" in law or "_" in law:
        return law
    return law.rstrip() + "%"


def strip_colontituls(text: str) -> str:
    out: list[str] = []
    for para in text.split("\n\n"):
        lines = []
        for line in para.split("\n"):
            s = line.strip()
            if COLONTITUL_LINE.match(s):
                continue
            s = COLONTITUL_TAIL.sub("", s).strip()
            if s:
                lines.append(s)
        if lines:
            out.append("\n".join(lines))
    return "\n\n".join(out)


def _line_starts_article(line: str) -> bool:
    return bool(RE_ARTICLE_HEADING.match(line.strip()))


def _count_structural_articles(text: str) -> int:
    """Capital «Статья N» (strict или голая строка)."""
    from structure_headings import RE_ARTICLE_BARE, RE_ARTICLE_HEADING_STRICT

    n = 0
    for line in text.split("\n"):
        s = line.strip()
        if RE_ARTICLE_HEADING_STRICT.match(s) or RE_ARTICLE_BARE.match(s):
            n += 1
    return n


def _count_gost_sections(text: str) -> int:
    """Нумерация вида «4.2 Заголовок», не «1 Введение»."""
    n = 0
    for para in text.split("\n\n"):
        for line in para.split("\n"):
            m = RE_GOST_SECTION_STRICT.match(line.strip())
            if m and "." in m.group(1):
                n += 1
    return n


def detect_doc_kind(text: str, title: str, explicit: str) -> str | None:
    explicit = (explicit or "auto").lower()
    if explicit in ("code", "gost", "sdank"):
        return explicit
    if explicit == "none":
        return None
    sample = f"{title}\n{text[:8000]}"
    if _count_structural_articles(text) >= 2:
        return "code"
    if re.search(r"(?i)\bСДАНК\b", sample):
        return "sdank"
    if re.search(r"(?i)\b(?:ГОСТ(?:\s*Р)?|СТО)\b", sample) and _count_gost_sections(text) >= 2:
        return "gost"
    if RE_CASUAL_ARTICLE.search(text):
        return None
    return None


def _meta_source_text(text: str, source_title: str) -> str:
    """Сырой текст первой страницы для извлечения law/redaction/effective_date."""
    chunk = text
    m = re.search(r"<!--\s*страница\s+2\s*-->", text)
    if m:
        chunk = text[: m.start()]
    elif len(chunk) > 12000:
        chunk = chunk[:12000]
    return f"{source_title}\n\n{chunk}"


def _document_header_blob(text: str, source_title: str) -> str:
    """Шапка: title + короткий преамбульный блок до первой структуры."""
    from structure_headings import RE_ARTICLE_BARE, RE_ARTICLE_HEADING_STRICT

    chunks = [source_title]
    for para in text.split("\n\n"):
        first = para.strip().split("\n")[0].strip() if para.strip() else ""
        if RE_ARTICLE_HEADING_STRICT.match(first) or RE_ARTICLE_BARE.match(first):
            break
        if re.match(r"^\d+\.\s+[A-ZА-ЯЁ]", first):
            break
        if re.match(r"^\d+(?:\.\d+)+\s+[A-ZА-ЯЁ]", first):
            break
        if re.match(r"^\d+\s+[A-ZА-ЯЁ]", first) and not RE_FZ_LINE.match(first):
            break
        chunks.append(para)
        if len(chunks) >= 3 or len("\n\n".join(chunks)) > 1200:
            break
    return "\n\n".join(chunks)


def extract_document_meta(
    text: str, options: DocImportOptions
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    header = _document_header_blob(text, options.source_title)
    red = options.redaction
    eff = normalize_date(options.effective_date)
    if not red:
        m = RE_REDACTION.search(header)
        if m:
            red = f"ред. от {m.group(1)}"
    if not eff:
        m = RE_INTRO_DATE.search(header)
        if m:
            eff = normalize_date(m.group(1))
    if not eff and red:
        m = RE_REDACTION.search(red)
        if m:
            eff = normalize_date(m.group(1))
    body_red = RE_REDACTION.search(text[ len(header) :])
    body_eff = RE_EFFECTIVE.search(text[len(header) :])
    meta_warn: str | None = None
    if body_red and not RE_REDACTION.search(header):
        meta_warn = "redaction_in_body_ignored"
    if body_eff and eff and RE_REDACTION.search(header):
        meta_warn = meta_warn or "effective_in_body_ignored"
    law = None
    standard = None
    for blob in (header, options.source_title):
        m = RE_LAW.search(blob)
        if m:
            law = re.sub(r"\s+", " ", m.group(1)).strip()
            break
        m = RE_LAW_FZ.search(blob)
        if m:
            law = m.group(1).upper().replace("фз", "ФЗ")
            break
        m = RE_LAW_FULL.search(blob)
        if m:
            law = re.sub(r"\s+", " ", m.group(1)).strip()[:120]
            break
    sm = RE_STANDARD_TITLE.search(header)
    if not sm:
        sm = RE_STANDARD_TITLE.search(options.source_title)
    if sm:
        standard = sm.group(1).strip().rstrip(".")
    return red, eff, law if law else None, standard, meta_warn


def _volume_heading_clears_article(
    heading_state: ArticleHeadingState | None,
    line_state: StructureLineState | None,
) -> bool:
    if heading_state is None:
        return True
    if not heading_state.in_toc_run:
        return True
    if heading_state.last_article is not None:
        return True
    if heading_state.after_toc_restart:
        return True
    if line_state is not None and line_state.after_page_break:
        return True
    return False


def _update_ctx_from_paragraph(
    ctx: StructureContext,
    para: str,
    *,
    heading_state: ArticleHeadingState | None = None,
    prev_line: str = "",
    line_state: StructureLineState | None = None,
) -> bool:
    """Обновляет контекст; True если жёсткая граница (новый пункт/статья/раздел)."""
    hard = False
    s = para.strip()
    if not s or s.startswith("<!--"):
        return False
    if is_paren_boundary_line(s) and ctx.article:
        return False

    if heading_state is not None and ctx.doc_kind == "code":
        ls = line_state if line_state is not None else StructureLineState(
            prev_line=prev_line, at_doc_start=not prev_line.strip()
        )
        num, title = accept_article_heading(
            s, heading_state, doc_kind=ctx.doc_kind, line_state=ls
        )
        if num:
            ctx.article = num
            if title:
                ctx.article_title = title.strip()
            ctx.point = None
            ctx.subpoint = None
            if line_state is not None:
                line_state.prev_list_style = None
            t = (title or "").strip()
            if (
                t
                and not t.rstrip().endswith(":")
                and not RE_POINT.match(t)
                and not RE_SUBPOINT.match(t)
                and (
                    re.search(r"[;(«\"]", t)
                    or re.search(
                        r"(?i)\b(?:ввести|признать|установить|настоящ(?:ий|ая|им))\b",
                        t,
                    )
                    or (len(t) < 120 and re.match(r"(?i)^текст\s+", t))
                )
            ):
                ctx.point = "1"
            return True
        if is_toc_heading_line(s):
            return True

    if ctx.doc_kind == "code" and is_strict_code_chapter_heading(s):
        m = RE_CHAPTER.match(s)
        if m:
            ch = m.group(1)
            if str(ctx.chapter or "") == ch:
                ctx.chapter = ch
                return False
            ctx.chapter = ch
        if heading_state is not None:
            heading_state.allow_large_forward = True
        if heading_state is None or _volume_heading_clears_article(
            heading_state, line_state
        ):
            ctx.article = None
            ctx.article_title = None
            ctx.point = None
            ctx.subpoint = None
        return True

    if ctx.doc_kind == "code" and is_strict_code_paragraph_heading(s):
        if heading_state is not None:
            heading_state.allow_large_forward = True
        if heading_state is None or _volume_heading_clears_article(
            heading_state, line_state
        ):
            ctx.article = None
            ctx.article_title = None
            ctx.point = None
            ctx.subpoint = None
        return True

    m = RE_PART.match(s)
    if m:
        part = m.group(1)
        if not part:
            w = s.split()[1].lower() if len(s.split()) > 1 else ""
            part = PART_WORDS.get(w, w)
        if part:
            ctx.law = ctx.law or f"ч. {part}"
        return False

    if ctx.doc_kind == "code" and (
        is_strict_code_section_heading(s) or is_strict_code_subsection_heading(s)
    ):
        if heading_state is not None:
            heading_state.allow_large_forward = True
        if heading_state is None or _volume_heading_clears_article(
            heading_state, line_state
        ):
            ctx.article = None
            ctx.article_title = None
            ctx.point = None
            ctx.subpoint = None
        return True

    m = RE_ANNEX.match(s)
    if m:
        ctx.annex = m.group(1)
        ctx.section_path = []
        ctx.point = None
        return True

    m = RE_GOST_SECTION_STRICT.match(s)
    if ctx.doc_kind in ("gost", "sdank") and m:
        from structure_headings import RE_FZ_WRAP_LINE

        if (
            RE_FZ_LINE.match(s)
            or RE_FZ_WRAP_LINE.match(s)
            or RE_DATE_LINE.match(s)
            or RE_DANGLING_REF.search(prev_line.strip())
        ):
            return False
        num = m.group(1)
        depth = num.count(".")
        path = ctx.section_path or []
        if depth == 0:
            path = [num]
        else:
            path = path[:depth] + [num]
        ctx.section_path = path
        ctx.point = None
        return True

    if ctx.doc_kind == "code":
        ls = line_state if line_state is not None else StructureLineState(
            prev_line=prev_line, at_doc_start=not prev_line.strip()
        )
        pid, pkind = accept_code_point_line(s, ls)
        if pid and pkind == "point":
            ctx.point = pid
            ctx.subpoint = None
            if line_state is not None and line_state.prev_list_style != "paren_point":
                line_state.prev_list_style = "dot_point"
            return True
        if pid and pkind == "subpoint":
            ctx.subpoint = pid
            if line_state is not None and line_state.prev_list_style != "paren_sub":
                line_state.prev_list_style = "paren_sub"
            return True

    return hard


def _split_colontitel_inline_point(
    line: str,
    *,
    after_page_break: bool,
    repeated_headers: set[str] | None = None,
) -> list[str]:
    """PDF-колонтитул и «2. …» на одной строке после маркера страницы."""
    s = line.strip()
    if not s or not after_page_break:
        return [s] if s else []
    rep = repeated_headers or set()
    split_at: tuple[str, str] | None = None
    for m in RE_INLINE_POINT_START.finditer(s):
        idx = m.start(1)
        head, tail = s[:idx].strip(), s[idx:].strip()
        if len(head) < 8 or len(head) > 220:
            continue
        if not RE_POINT.match(tail) or RE_POINT.match(head):
            continue
        if is_consultant_running_header_prefix(head) or head in rep:
            split_at = (head, tail)
    if split_at:
        return [split_at[0], split_at[1]]
    return [s]


def _expand_structure_lines(
    para: str,
    *,
    heading_state: ArticleHeadingState | None = None,
    doc_kind: str | None = None,
    prev_line: str = "",
    prev_was_structure_heading: bool = False,
    at_doc_start: bool = True,
    after_page_break: bool = False,
    repeated_headers: set[str] | None = None,
) -> list[str]:
    """Строки абзаца; не изменяет общий line_state (Q3)."""
    out: list[str] = []
    local_prev = prev_line
    local_was = prev_was_structure_heading
    local_start = at_doc_start
    local_pb = after_page_break
    for raw in para.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if heading_state and doc_kind == "code":
            peek = ArticleHeadingState(
                last_article=heading_state.last_article,
                lowercase_headings=heading_state.lowercase_headings,
                after_toc_restart=heading_state.after_toc_restart,
                in_toc_run=heading_state.in_toc_run,
                consecutive_heading_lines=heading_state.consecutive_heading_lines,
            )
            peek_ls = StructureLineState(
                prev_line=local_prev,
                at_doc_start=local_start,
                after_page_break=local_pb,
                heading=peek,
                prev_was_structure_heading=local_was,
            )
            num, _ = accept_article_heading(
                line, peek, doc_kind=doc_kind, line_state=peek_ls
            )
            if num:
                out.append(line)
                local_prev = line
                local_was = True
                local_start = False
                local_pb = False
                continue
        for piece in _split_colontitel_inline_point(
            line,
            after_page_break=local_pb,
            repeated_headers=repeated_headers,
        ):
            for seg in split_inline_article_segments(piece):
                if seg:
                    out.append(seg)
                    local_prev = seg
                    local_was = is_structure_heading_line(seg)
                    local_start = False
                    local_pb = False
    return out or ([para.strip()] if para.strip() else [])


def _collapse_orphan_heading_atoms(atoms: list[dict]) -> list[dict]:
    """Заголовок без пункта перед тем же article+p.1 — влить в первый пункт (оглавление глав)."""
    out: list[dict] = []
    i = 0
    while i < len(atoms):
        a = atoms[i]
        meta = a.get("structure_meta") or {}
        if (
            meta.get("article")
            and not meta.get("point")
            and i + 1 < len(atoms)
        ):
            nxt = atoms[i + 1]
            nm = nxt.get("structure_meta") or {}
            if nm.get("article") == meta.get("article") and nm.get("point"):
                nxt = {**nxt, "content": a["content"] + " " + nxt["content"]}
                out.append(nxt)
                i += 2
                continue
        out.append(a)
        i += 1
    return out


def _carry_article_over_chapter_colontitel(atoms: list[dict]) -> list[dict]:
    """После колонтитула «Глава N» пункт без article — наследует предыдущую статью."""
    out: list[dict] = []
    last_article: str | None = None
    for a in atoms:
        meta = dict(a.get("structure_meta") or {})
        if meta.get("article"):
            last_article = str(meta["article"])
        elif (
            last_article
            and meta.get("point")
            and not meta.get("article")
            and meta.get("chapter")
        ):
            meta["article"] = last_article
            a = {**a, "structure_meta": meta}
        out.append(a)
    return out


def _merge_volume_heading_atoms(atoms: list[dict]) -> list[dict]:
    """«Глава/Раздел/§ …» без статьи — влить в следующий атом (не терять текст в quality_gate)."""
    out: list[dict] = []
    i = 0
    while i < len(atoms):
        a = atoms[i]
        meta = a.get("structure_meta") or {}
        content = a.get("content", "").strip()
        if (
            not meta.get("article")
            and not meta.get("point")
            and i + 1 < len(atoms)
            and is_strict_code_volume_heading(content)
        ):
            nxt = dict(atoms[i + 1])
            nxt["content"] = content + " " + nxt.get("content", "").lstrip()
            nxt["page"] = nxt.get("page") or a.get("page")
            out.append(nxt)
            i += 2
            continue
        out.append(a)
        i += 1
    return out


def _merge_heading_atoms(atoms: list[dict]) -> list[dict]:
    merged: list[dict] = []
    i = 0
    while i < len(atoms):
        a = atoms[i]
        content = a.get("content", "")
        meta = a.get("structure_meta") or {}
        if RE_ARTICLE_HEADING.match(content.strip()) and len(content) < 120 and i + 1 < len(atoms):
            nxt = atoms[i + 1]
            if (nxt.get("structure_meta") or {}).get("article") == meta.get("article"):
                nxt = {**nxt, "content": content + " " + nxt["content"]}
                merged.append(nxt)
                i += 2
                continue
        merged.append(a)
        i += 1
    return merged


def _attach_preamble(atoms: list[dict]) -> list[dict]:
    if not atoms:
        return atoms
    pre: list[str] = []
    rest = atoms
    while rest and not (rest[0].get("structure_meta") or {}).get("article"):
        pre.append(rest[0]["content"])
        rest = rest[1:]
    if pre and rest:
        rest[0] = {**rest[0], "content": " ".join(pre + [rest[0]["content"]])}
    elif pre:
        return [{"content": " ".join(pre), "atom_type": "text", "structure_meta": atoms[0].get("structure_meta", {})}]
    return rest


def _split_sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n\n", text) if p.strip()]


def _pack_block(text: str, meta: dict, chunk_max: int) -> list[dict]:
    sents = _split_sentences(text)
    if not sents:
        return []
    atoms: list[dict] = []
    current = ""
    for sent in sents:
        if len(current) + len(sent) <= chunk_max or not current:
            current = current + (" " if current else "") + sent
        else:
            atoms.append({"content": current, "atom_type": "text", "structure_meta": dict(meta)})
            current = sent
    if current:
        atoms.append({"content": current, "atom_type": "text", "structure_meta": dict(meta)})
    return atoms


def _repeated_header_line_counts(text: str) -> Counter[str]:
    from collections import Counter

    per_page: dict[int | None, set[str]] = {}
    page: int | None = None
    for para in text.split("\n\n"):
        marks = PAGE_MARK.findall(para)
        if marks:
            page = int(marks[-1])
        body = PAGE_MARK.sub("", para).strip()
        for raw in body.split("\n"):
            s = raw.strip()
            if s and not s.startswith("<!--"):
                per_page.setdefault(page, set()).add(s)
    counts: Counter[str] = Counter()
    for lines in per_page.values():
        for ln in lines:
            counts[ln] += 1
    return counts


def _page_initial_line_counts(text: str) -> Counter[str]:
    from collections import Counter

    first_on_page: Counter[str] = Counter()
    page: int | None = None
    seen_page: set[int] = set()
    for para in text.split("\n\n"):
        marks = PAGE_MARK.findall(para)
        if marks:
            page = int(marks[-1])
        body = PAGE_MARK.sub("", para).strip()
        if not body or page is None or page in seen_page:
            continue
        first = body.split("\n")[0].strip()
        if first:
            first_on_page[first] += 1
            seen_page.add(page)
    return first_on_page


def _repeated_header_lines(text: str) -> set[str]:
    from collections import Counter

    per_page: dict[int, set[str]] = {}
    page = 1
    for para in text.split("\n\n"):
        marks = PAGE_MARK.findall(para)
        if marks:
            page = int(marks[-1])
        body = PAGE_MARK.sub("", para).strip()
        for raw in body.split("\n"):
            s = raw.strip()
            if s and not s.startswith("<!--"):
                per_page.setdefault(page, set()).add(s)
    counts: Counter[str] = Counter()
    for lines in per_page.values():
        for ln in lines:
            counts[ln] += 1
    page_tops = {ln for ln, n in _page_initial_line_counts(text).items() if n >= 2}
    repeated = {
        ln
        for ln, n in counts.items()
        if n >= 3 or (n >= 2 and is_strict_code_volume_heading(ln))
    }
    repeated |= page_tops
    from structure_headings import is_repeatable_colontitel_shape

    repeated |= {
        ln
        for ln, n in counts.items()
        if n >= 2 and is_repeatable_colontitel_shape(ln)
    }
    return repeated


def structure_split(
    text: str,
    ctx: StructureContext,
    *,
    chunk_max: int = 500,
    chunk_min: int = 300,
) -> list[dict]:
    """Нарезка с жёсткими границами структуры; длинные блоки режутся по предложениям."""
    header_counts = _repeated_header_line_counts(text)
    repeated_headers = _repeated_header_lines(text)
    paragraphs: list[tuple[int | None, str]] = []
    page: int | None = None
    for para in text.split("\n\n"):
        marks = PAGE_MARK.findall(para)
        if marks:
            page = int(marks[-1])
        body = PAGE_MARK.sub("", para).strip()
        if not body:
            continue
        paragraphs.append((page, body))

    heading_state = ArticleHeadingState(
        lowercase_headings=detect_lowercase_heading_style(text)
    )
    line_state = StructureLineState(heading=heading_state)
    blocks: list[tuple[StructureContext, str, int | None]] = []
    cur_ctx = ctx.copy()
    cur_page: int | None = None
    block_start_page: int | None = None
    cur_parts: list[str] = []
    cur_key = cur_ctx.boundary_key()
    in_title_block = True

    def flush():
        nonlocal cur_parts, block_start_page
        if not cur_parts:
            return
        blocks.append((cur_ctx.copy(), " ".join(cur_parts), block_start_page))
        cur_parts = []

    for pg, para in paragraphs:
        if pg is not None and pg != cur_page:
            if cur_parts:
                flush()
            cur_page = pg
            cur_ctx.page = pg
            block_start_page = cur_page
            line_state.after_page_break = True
        else:
            if not line_state.preserve_page_break:
                line_state.after_page_break = False
        lines = _expand_structure_lines(
            para,
            heading_state=heading_state,
            doc_kind=cur_ctx.doc_kind,
            prev_line=line_state.prev_line,
            prev_was_structure_heading=line_state.prev_was_structure_heading,
            at_doc_start=line_state.at_doc_start,
            after_page_break=line_state.after_page_break,
            repeated_headers=repeated_headers,
        )
        for line in lines:
            n_rep = header_counts.get(line, 0)
            same_chapter_colontitel = False
            if is_strict_code_chapter_heading(line):
                ch_m = RE_CHAPTER.match(line)
                if ch_m and str(cur_ctx.chapter or "") == ch_m.group(1):
                    same_chapter_colontitel = True
            body_chapter_dup = (
                is_strict_code_volume_heading(line)
                and heading_state.last_article is not None
                and n_rep == 2
                and not same_chapter_colontitel
            )
            if in_title_block and (
                is_strict_code_volume_heading(line)
                or is_structure_heading_line(line)
                or RE_POINT.match(line)
                or RE_SUBPOINT.match(line)
            ):
                in_title_block = False
            running = same_chapter_colontitel or is_running_header_line(
                line,
                repeated=line in repeated_headers and not body_chapter_dup,
                skip_title_block=in_title_block,
                page_top_after_break=line_state.after_page_break,
            )
            if line_state.preserve_page_break:
                line_state.after_page_break = True
                line_state.preserve_page_break = False
            update_toc_state(
                line_state,
                line,
                skip_volume_reset=(
                    same_chapter_colontitel
                    or (running and is_strict_code_volume_heading(line))
                ),
            )
            if running:
                if cur_parts:
                    flush()
                banner_ctx = cur_ctx.copy()
                banner_ctx.article = None
                banner_ctx.point = None
                banner_ctx.subpoint = None
                blocks.append((banner_ctx, line, block_start_page))
                line_state.preserve_page_break = (
                    line_state.after_page_break or line_state.preserve_page_break
                )
                line_state.prev_line = line
                line_state.at_doc_start = False
                line_state.after_page_break = False
                line_state.prev_was_structure_heading = is_structure_heading_line(
                    line
                )
                continue
            new_ctx = cur_ctx.copy()
            hard = _update_ctx_from_paragraph(
                new_ctx,
                line,
                heading_state=heading_state,
                line_state=line_state,
            )
            line_state.prev_line = line
            line_state.at_doc_start = False
            line_state.after_page_break = False
            line_state.prev_was_structure_heading = is_structure_heading_line(line)
            new_key = new_ctx.boundary_key()
            if hard or (cur_parts and new_key != cur_key):
                flush()
                block_start_page = cur_page
            elif not cur_parts:
                block_start_page = cur_page
            cur_ctx = new_ctx
            cur_key = new_key
            cur_parts.append(line)

    flush()

    atoms: list[dict] = []
    for block_ctx, content, pg in blocks:
        meta = block_ctx.metadata()
        if pg is not None:
            meta["page"] = pg
        if len(content) <= chunk_max:
            atoms.append(
                {
                    "content": content,
                    "atom_type": "text",
                    "page": pg,
                    "structure_meta": meta,
                }
            )
        else:
            for piece in _pack_block(content, meta, chunk_max):
                piece["page"] = pg
                atoms.append(piece)

    merged: list[dict] = []
    for a in atoms:
        if (
            merged
            and len(a["content"]) < chunk_min
            and merged[-1].get("structure_meta") == a.get("structure_meta")
            and len(merged[-1]["content"]) + len(a["content"]) < chunk_max * 1.5
        ):
            merged[-1]["content"] += " " + a["content"]
            merged[-1]["page"] = merged[-1].get("page") or a.get("page")
        else:
            merged.append(a)
    merged = _merge_heading_atoms(merged)
    if ctx.doc_kind == "code":
        merged = _collapse_orphan_heading_atoms(merged)
        merged = _merge_volume_heading_atoms(merged)
        merged = _carry_article_over_chapter_colontitel(merged)
        merged = _attach_preamble(merged)
    return merged


def build_page_context_map(text: str, ctx: StructureContext) -> dict[int, dict[str, Any]]:
    """Контекст структуры по номеру страницы (для таблиц/рисунков)."""
    out: dict[int, dict[str, Any]] = {}
    cur = ctx.copy()
    page: int | None = None
    hs = ArticleHeadingState(lowercase_headings=detect_lowercase_heading_style(text))
    ls = StructureLineState(heading=hs)
    for para in text.split("\n\n"):
        marks = PAGE_MARK.findall(para)
        if marks:
            page = int(marks[-1])
            cur.page = page
            ls.after_page_break = True
        body = PAGE_MARK.sub("", para).strip()
        repeated_headers = _repeated_header_lines(text)
        for line in _expand_structure_lines(
            body,
            heading_state=hs,
            doc_kind=cur.doc_kind,
            prev_line=ls.prev_line,
            prev_was_structure_heading=ls.prev_was_structure_heading,
            at_doc_start=ls.at_doc_start,
            after_page_break=ls.after_page_break,
        ):
            if is_running_header_line(
                line, repeated=line in repeated_headers
            ):
                continue
            update_toc_state(ls, line)
            _update_ctx_from_paragraph(
                cur, line, heading_state=hs, line_state=ls
            )
            ls.prev_line = line
            ls.at_doc_start = False
            ls.after_page_break = False
            ls.prev_was_structure_heading = is_structure_heading_line(line)
            if page is not None:
                out[page] = cur.metadata()
    return out


def prepare_for_import(
    md: str,
    options: DocImportOptions,
    *,
    meta_source: str | None = None,
) -> tuple[str, StructureContext | None, dict[int, dict[str, Any]]]:
    cleaned = strip_colontituls(md)
    kind = detect_doc_kind(cleaned, options.source_title, options.doc_kind)
    if not kind:
        return md, None, {}
    meta_blob = _meta_source_text(meta_source or md, options.source_title)
    red, eff, law, standard, meta_warn = extract_document_meta(meta_blob, options)
    ctx = StructureContext(
        doc_kind=kind, law=law, standard=standard, redaction=red, effective_date=eff
    )
    if options.redaction:
        ctx.redaction_source = "param"
    elif red:
        ctx.redaction_source = "auto"
    page_map = build_page_context_map(cleaned, ctx)
    if meta_warn == "redaction_in_body_ignored":
        print(
            "      ⚠ «ред. от …» найдено только в тексте статей — effective_date не задан",
            file=sys.stderr,
        )
    elif (
        ctx.doc_kind == "code"
        and not ctx.effective_date
        and RE_REDACTION.search(cleaned[:8000])
    ):
        print(
            "      ⚠ в тексте есть «ред. от …», но effective_date не задан — as-of может вести себя как для недатированного источника",
            file=sys.stderr,
        )
    return cleaned, ctx, page_map


def format_citation(meta: dict, source_title: str) -> str:
    """Человекочитаемая цитата для выдачи (VS-15)."""
    meta = meta or {}
    page = meta.get("page") or "?"
    red = meta.get("redaction")
    red_part = f" ({red})" if red else ""
    kind = meta.get("doc_kind")

    if (kind == "code" or meta.get("article")) and kind not in ("gost", "sdank"):
        head = meta.get("law") or source_title
        parts = [head]
        if meta.get("article"):
            parts.append(f"ст. {meta['article']}")
        if meta.get("point"):
            parts.append(f"п. {meta['point']}")
        if meta.get("subpoint"):
            parts.append(f"пп. {meta['subpoint']}")
        return f"{', '.join(parts)}{red_part}, стр. {page}"

    sp = meta.get("section_path")
    title = meta.get("standard") or meta.get("law") or source_title
    m = RE_STANDARD_TITLE.search(title) or RE_STANDARD_TITLE.search(source_title)
    if m:
        title = m.group(1)
    if meta.get("annex"):
        return f"{title}, приложение {meta['annex']}{red_part}, стр. {page}"
    if sp:
        leaf = sp[-1] if isinstance(sp, list) else str(sp)
        return f"{title}, п. {leaf}{red_part}, стр. {page}"
    return f"{title}{red_part}, стр. {page}"
