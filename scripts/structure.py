"""Структурная нарезка кодексов и нормативных документов (VS-14, VS-15)."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
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


def normalize_date(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip()
    m = re.match(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})", s)
    if not m:
        return s
    d, mo, y = m.groups()
    if len(y) == 2:
        y = "20" + y
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"


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


def detect_doc_kind(text: str, title: str, explicit: str) -> str | None:
    explicit = (explicit or "auto").lower()
    if explicit in ("code", "gost", "sdank"):
        return explicit
    if explicit == "none":
        return None
    sample = f"{title}\n{text[:8000]}"
    if len(re.findall(r"(?i)(?:^|\s)статья\s+\d+", text)) >= 2:
        return "code"
    if re.search(r"(?i)\bСДАНК\b", sample):
        return "sdank"
    if re.search(r"(?i)\bГОСТ(?:\s*Р)?\b", sample) or re.search(
        r"^\d+(?:\.\d+){1,3}\s+\S", text, re.MULTILINE
    ):
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
        m = RE_EFFECTIVE.search(text[:12000])
        if m:
            eff = normalize_date(m.group(1))
    law = None
    m = RE_LAW.search(text[:5000]) or RE_LAW.search(options.source_title)
    if m:
        law = re.sub(r"\s+", " ", m.group(1)).strip()
    return red, eff, law if law else None


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
        ctx.section_path = [f"Приложение {ctx.annex}"]
        return True

    m = RE_GOST_SECTION.match(s)
    if ctx.doc_kind in ("gost", "sdank") and m:
        num = m.group(1)
        depth = num.count(".")
        path = ctx.section_path or []
        if depth == 0:
            path = [num]
        else:
            path = path[:depth] + [num]
        ctx.section_path = path
        ctx.point = num.split(".")[-1]
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
    cur_parts: list[str] = []
    cur_key = cur_ctx.boundary_key()

    def flush():
        nonlocal cur_parts, cur_key, cur_page
        if not cur_parts:
            return
        blocks.append((cur_ctx.copy(), " ".join(cur_parts), cur_page))
        cur_parts = []

    for pg, para in paragraphs:
        if pg is not None:
            cur_page = pg
            cur_ctx.page = pg
        lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        if not lines:
            lines = [para.strip()] if para.strip() else []
        for line in lines:
            new_ctx = cur_ctx.copy()
            hard = _update_ctx_from_paragraph(new_ctx, line)
            new_key = new_ctx.boundary_key()
            if hard or (cur_parts and new_key != cur_key):
                flush()
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
    if ctx.doc_kind == "code":
        merged = [
            a
            for a in merged
            if a.get("structure_meta", {}).get("article")
            or a.get("structure_meta", {}).get("section_path")
        ]
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
        if body:
            _update_ctx_from_paragraph(cur, body)
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
    red, eff, law = extract_document_meta(cleaned, options)
    ctx = StructureContext(doc_kind=kind, law=law, redaction=red, effective_date=eff)
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
    title = source_title
    m = RE_STANDARD_TITLE.search(source_title)
    if m:
        title = m.group(1)
    if sp:
        leaf = sp[-1] if isinstance(sp, list) else str(sp)
        return f"{title}, п. {leaf}{red_part}, стр. {page}"
    if meta.get("annex"):
        return f"{title}, приложение {meta['annex']}{red_part}, стр. {page}"
    return f"{title}{red_part}, стр. {page}"
