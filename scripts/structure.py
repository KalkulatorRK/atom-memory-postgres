"""Структурная нарезка кодексов и нормативных документов (VS-14, VS-15)."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

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
    r"^(?:Статья|СТАТЬЯ)\s+(\d+(?:\.\d+)?)(?:[.\s—–-]\s*(.*))?$",
    re.IGNORECASE,
)
RE_CHAPTER = re.compile(r"^(?:Глава|ГЛАВА)\s+(\d+)", re.IGNORECASE)
RE_PART = re.compile(
    r"^Часть\s+(?:первая|вторая|третья|четв[её]ртая|пят(?:ая|ая)|(\d+))",
    re.IGNORECASE,
)
RE_SECTION_CODE = re.compile(
    r"^(?:Раздел|РАЗДЕЛ|Подраздел|ПОДРАЗДЕЛ)\s+([IVX\d]+)",
    re.IGNORECASE,
)
RE_POINT = re.compile(r"^(\d+)\.\s+")
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
    r"\b((?:ГОСТ(?:\s*Р)?|СДАНК|СТО|ISO)\s*[-\w.]+)",
    re.IGNORECASE,
)
RE_ARTICLE_HEADING = re.compile(r"^(?:Статья|СТАТЬЯ)\s+(\d+(?:\.\d+)?)\b")
RE_ARTICLE_HEADING_CI = re.compile(
    r"^(?:Статья|СТАТЬЯ|статья)\s+(\d+(?:\.\d+)?)\b", re.IGNORECASE
)
RE_ARTICLE_INLINE = re.compile(
    r"(?<=[.;!?])\s+(?=(?:Статья|СТАТЬЯ)\s+\d+)", re.IGNORECASE
)
RE_CASUAL_ARTICLE = re.compile(r"(?:^|[\s,.;(])стать(?:я|и|ей|ю)\s+\d+")
RE_GOST_SECTION_STRICT = re.compile(
    r"^(\d+(?:\.\d+){0,4})\s+([A-ZА-ЯЁ«\"].*)"
)
RE_INTRO_DATE = re.compile(
    r"(?:Дата\s+введения|дата\s+введения)\s*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    re.IGNORECASE,
)

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
    """Заголовки «Статья N» в начале строки (не «статья N договора»)."""
    n = 0
    for line in text.split("\n"):
        if RE_ARTICLE_HEADING.match(line.strip()):
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
    if RE_CASUAL_ARTICLE.search(text):
        return None
    if re.search(r"(?i)\bСДАНК\b", sample):
        return "sdank"
    if re.search(r"(?i)\bГОСТ(?:\s*Р)?\b", sample) and _count_gost_sections(text) >= 2:
        return "gost"
    return None


def extract_document_meta(text: str, options: DocImportOptions) -> tuple[str | None, str | None, str | None]:
    red = options.redaction
    eff = normalize_date(options.effective_date)
    if not red:
        m = RE_REDACTION.search(text[:12000])
        if m:
            red = f"ред. от {m.group(1)}"
    if not eff:
        for rx in (RE_INTRO_DATE, RE_EFFECTIVE):
            m = rx.search(text[:12000])
            if m:
                eff = normalize_date(m.group(1))
                break
    law = None
    standard = None
    m = RE_LAW.search(text[:5000]) or RE_LAW.search(options.source_title)
    if m:
        law = re.sub(r"\s+", " ", m.group(1)).strip()
    sm = RE_STANDARD_TITLE.search(text[:5000]) or RE_STANDARD_TITLE.search(options.source_title)
    if sm:
        standard = sm.group(1).strip()
    return red, eff, law if law else None, standard


def _update_ctx_from_paragraph(ctx: StructureContext, para: str) -> bool:
    """Обновляет контекст; True если жёсткая граница (новый пункт/статья/раздел)."""
    hard = False
    s = para.strip()
    if not s or s.startswith("<!--"):
        return False

    m = RE_ARTICLE.match(s)
    if m:
        ctx.article = m.group(1)
        ctx.article_title = (m.group(2) or "").strip() or ctx.article_title
        ctx.point = None
        ctx.subpoint = None
        return True

    m = RE_CHAPTER.match(s)
    if m:
        ctx.chapter = m.group(1)
        return False

    m = RE_PART.match(s)
    if m:
        part = m.group(1)
        if not part:
            w = s.split()[1].lower() if len(s.split()) > 1 else ""
            part = PART_WORDS.get(w, w)
        if part:
            ctx.law = ctx.law or f"ч. {part}"
        return False

    if RE_SECTION_CODE.match(s):
        return False

    m = RE_ANNEX.match(s)
    if m:
        ctx.annex = m.group(1)
        ctx.section_path = []
        ctx.point = None
        return True

    m = RE_GOST_SECTION_STRICT.match(s)
    if ctx.doc_kind in ("gost", "sdank") and m:
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

    m = RE_POINT.match(s)
    if ctx.doc_kind == "code" and m:
        ctx.point = m.group(1)
        ctx.subpoint = None
        return True

    m = RE_SUBPOINT.match(s)
    if ctx.doc_kind == "code" and m:
        ctx.subpoint = m.group(1)
        return True

    return hard


def _expand_structure_lines(para: str) -> list[str]:
    out: list[str] = []
    for raw in para.split("\n"):
        line = raw.strip()
        if not line:
            continue
        parts = RE_ARTICLE_INLINE.split(line)
        for p in parts:
            p = p.strip()
            if not p:
                continue
            for seg in re.split(r"(?=(?:(?:Статья|СТАТЬЯ)\s+\d+))", p, flags=re.IGNORECASE):
                seg = seg.strip()
                if seg:
                    out.append(seg)
    return out or ([para.strip()] if para.strip() else [])


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


def structure_split(
    text: str,
    ctx: StructureContext,
    *,
    chunk_max: int = 500,
    chunk_min: int = 300,
) -> list[dict]:
    """Нарезка с жёсткими границами структуры; длинные блоки режутся по предложениям."""
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

    blocks: list[tuple[StructureContext, str, int | None]] = []
    cur_ctx = ctx.copy()
    cur_page = page
    block_start_page = page
    cur_parts: list[str] = []
    cur_key = cur_ctx.boundary_key()

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
        lines = _expand_structure_lines(para)
        for line in lines:
            new_ctx = cur_ctx.copy()
            hard = _update_ctx_from_paragraph(new_ctx, line)
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
        merged = _attach_preamble(merged)
    return merged


def build_page_context_map(text: str, ctx: StructureContext) -> dict[int, dict[str, Any]]:
    """Контекст структуры по номеру страницы (для таблиц/рисунков)."""
    out: dict[int, dict[str, Any]] = {}
    cur = ctx.copy()
    page: int | None = None
    for para in text.split("\n\n"):
        marks = PAGE_MARK.findall(para)
        if marks:
            page = int(marks[-1])
            cur.page = page
        body = PAGE_MARK.sub("", para).strip()
        for line in _expand_structure_lines(body):
            _update_ctx_from_paragraph(cur, line)
            if page is not None:
                out[page] = cur.metadata()
    return out


def prepare_for_import(
    md: str, options: DocImportOptions
) -> tuple[str, StructureContext | None, dict[int, dict[str, Any]]]:
    cleaned = strip_colontituls(md)
    kind = detect_doc_kind(cleaned, options.source_title, options.doc_kind)
    if not kind:
        return md, None, {}
    red, eff, law, standard = extract_document_meta(cleaned, options)
    ctx = StructureContext(
        doc_kind=kind, law=law, standard=standard, redaction=red, effective_date=eff
    )
    if options.redaction:
        ctx.redaction_source = "param"
    elif red:
        ctx.redaction_source = "auto"
    page_map = build_page_context_map(cleaned, ctx)
    return cleaned, ctx, page_map


def format_citation(meta: dict, source_title: str) -> str:
    """Человекочитаемая цитата для выдачи (VS-15)."""
    meta = meta or {}
    page = meta.get("page") or "?"
    red = meta.get("redaction")
    red_part = f" ({red})" if red else ""
    kind = meta.get("doc_kind")

    if kind == "code" or meta.get("article"):
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
