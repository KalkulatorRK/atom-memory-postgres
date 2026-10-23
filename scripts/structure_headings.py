"""Правила заголовков статей и пунктов (единый набор для normalize / split)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Заголовок: «Статья 12. Название» / «Статья 12 — …» / голая «Статья 1».
RE_ARTICLE_HEADING_STRICT = re.compile(
    r"^(?:Статья|СТАТЬЯ)\s+(\d+(?:\.\d+)*)"
    r"(?:\.\s+[0-9A-ZА-ЯЁ«\"(]|(?:\s*[—–-]\s*[0-9A-ZА-ЯЁ«\"(]))"
)
RE_ARTICLE_BARE = re.compile(r"^(?:Статья|СТАТЬЯ)\s+(\d+(?:\.\d+)*)\s*$")
RE_ARTICLE_REFERENCE = re.compile(
    r"^(?:Статья|СТАТЬЯ|статья)\s+(\d+(?:\.\d+)*)\s+"
    r"(?:настоящего|данного|этого|указанного|вышеупомянутого|кодекса)\b",
    re.IGNORECASE,
)
RE_ARTICLE_LOW_HEADING = re.compile(
    r"^статья\s+(\d+(?:\.\d+)*)\.\s+[A-ZА-ЯЁ«\"(]"
)
RE_INLINE_ARTICLE = re.compile(r"(?:Статья|СТАТЬЯ)\s+(\d+(?:\.\d+)*)")

RE_ABBREV_BEFORE_DOT = re.compile(
    r"(?i)\b(?:п|пп|ст|ч|разд|подп|абз|§|\d+)\.\s*$"
)

RE_TOC_TRAIL = re.compile(r"(?:\.{2,}|…)\s*\d+\s*$")
RE_POINT_LINE = re.compile(r"^(\d+(?:\.\d+)*)\.\s+(\S.*)$")
RE_SUBPOINT_LINE = re.compile(r"^(\d+)\)\s+(\S.*)$")

RE_REF_WORD_BEFORE_POINT = re.compile(
    r"(?i)(?:"
    r"\bп\.?\s*$|\bпункт(?:а|е|у)?\s*$|\bстать(?:я|и|ей|ью)\s*$|\bчаст(?:ь|и|ью)\s*$|"
    r"\bот\s*$|\b№\s*$|"
    r"\b(?:январ[яю]|феврал[яю]|март[а]?|апрел[яю]|ма[яй]|июн[яю]|июл[яю]|"
    r"август[а]?|сентябр[яю]|октябр[яю]|ноябр[яю]|декабр[яю])\s*$"
    r")"
)

RE_LOWERCASE_WORD_TAIL = re.compile(r"[а-яё]\s*$", re.IGNORECASE)


@dataclass
class ArticleHeadingState:
    last_article: tuple[int, ...] | None = None
    lowercase_headings: bool = False
    after_toc_restart: bool = False
    in_toc_run: bool = False


@dataclass
class StructureLineState:
    """Состояние между строками/абзацами (границы + оглавление)."""

    prev_line: str = ""
    at_doc_start: bool = True
    after_page_break: bool = False
    heading: ArticleHeadingState = field(default_factory=ArticleHeadingState)
    prev_was_article_heading: bool = False


def detect_lowercase_heading_style(text: str) -> bool:
    lower = upper = 0
    for line in text.split("\n"):
        s = line.strip()
        if RE_ARTICLE_LOW_HEADING.match(s):
            lower += 1
        elif RE_ARTICLE_HEADING_STRICT.match(s) or RE_ARTICLE_BARE.match(s):
            upper += 1
    return lower >= 2 and lower > upper


def article_number_tuple(raw: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(p) for p in raw.split("."))
    except ValueError:
        return None


def is_capital_article_heading(s: str) -> bool:
    return bool(
        RE_ARTICLE_HEADING_STRICT.match(s)
        or RE_ARTICLE_BARE.match(s)
    )


def is_real_sentence_end_before(text: str) -> bool:
    """Конец предложения/абзаца перед кандидатом в заголовок (не «п. 3.»)."""
    before = text.rstrip()
    if not before:
        return False
    if before[-1] not in ".:;!?":
        return False
    if before[-1] == "." and RE_ABBREV_BEFORE_DOT.search(before):
        return False
    return True


def boundary_before_structure(prev_line: str, *, line_state: StructureLineState) -> bool:
    """Заголовок/пункт допустим только после границы (N1/N2)."""
    if line_state.after_page_break:
        return True
    if line_state.at_doc_start:
        return True
    if line_state.heading.after_toc_restart:
        return True
    if not prev_line.strip():
        return False
    if line_state.prev_was_article_heading:
        return True
    return is_real_sentence_end_before(prev_line)


def is_toc_heading_line(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    if RE_TOC_TRAIL.search(s):
        return True
    if RE_ARTICLE_HEADING_STRICT.match(s) or RE_ARTICLE_BARE.match(s):
        if re.search(r"\.{3,}|…", s):
            return True
        if re.search(r"\s\d+\s*$", s) and not re.search(r"\.\s+[A-ZА-ЯЁ]", s):
            return True
    return False


def is_substantive_body_line(s: str) -> bool:
    s = s.strip()
    if not s or s.startswith("<!--"):
        return False
    if is_toc_heading_line(s):
        return False
    if RE_ARTICLE_HEADING_STRICT.match(s) or RE_ARTICLE_BARE.match(s):
        return False
    if RE_POINT_LINE.match(s) and len(s) > 20:
        return True
    if RE_SUBPOINT_LINE.match(s) and len(s) > 20:
        return True
    if re.match(r"^(?:Глава|Раздел|Часть)\s", s, re.IGNORECASE):
        return False
    return len(s) > 30


def update_toc_state(line_state: StructureLineState, line: str) -> None:
    s = line.strip()
    if is_toc_heading_line(s):
        line_state.heading.in_toc_run = True
        return
    if not line_state.heading.in_toc_run:
        return
    real_article = (RE_ARTICLE_HEADING_STRICT.match(s) or RE_ARTICLE_BARE.match(s)) and not is_toc_heading_line(s)
    if is_substantive_body_line(s) or real_article:
        line_state.heading.in_toc_run = False
        line_state.heading.after_toc_restart = True


def _accept_monotonic(
    state: ArticleHeadingState,
    num: tuple[int, ...],
    *,
    lowercase: bool,
    allow_restart: bool,
) -> bool:
    if state.last_article is None:
        return True
    if num > state.last_article:
        return True
    if num == state.last_article:
        return False
    if num < state.last_article:
        return allow_restart
    return False


def accept_article_heading(
    line: str,
    state: ArticleHeadingState,
    *,
    doc_kind: str | None,
    line_state: StructureLineState,
) -> tuple[str | None, str | None]:
    """Если строка — заголовок статьи, вернуть (номер, хвост); иначе (None, None)."""
    if doc_kind in ("gost", "sdank"):
        return None, None
    s = line.strip()
    if not s or RE_ARTICLE_REFERENCE.match(s):
        return None, None

    num_s: str | None = None
    lowercase = False
    if RE_ARTICLE_HEADING_STRICT.match(s):
        num_s = RE_ARTICLE_HEADING_STRICT.match(s).group(1)
    elif RE_ARTICLE_BARE.match(s):
        num_s = RE_ARTICLE_BARE.match(s).group(1)
    elif (
        doc_kind == "code"
        and state.lowercase_headings
        and RE_ARTICLE_LOW_HEADING.match(s)
    ):
        num_s = RE_ARTICLE_LOW_HEADING.match(s).group(1)
        lowercase = True

    if not num_s:
        return None, None

    if not boundary_before_structure(
        line_state.prev_line, line_state=line_state
    ):
        return None, None

    num = article_number_tuple(num_s)
    allow_restart = state.after_toc_restart and not lowercase
    if num is None or not _accept_monotonic(
        state, num, lowercase=lowercase, allow_restart=allow_restart
    ):
        return None, None

    state.last_article = num
    if allow_restart:
        state.after_toc_restart = False
    tail = s.split(None, 2)
    title = tail[2] if len(tail) > 2 else ""
    return num_s, title


def point_body_starts_ok(rest: str) -> bool:
    if not rest:
        return False
    return bool(re.match(r"^[A-ZА-ЯЁ«\"(0-9]", rest))


def accept_code_point_line(
    line: str,
    line_state: StructureLineState,
) -> tuple[str | None, str | None]:
    """Пункт/подпункт кодекса: (point_id, kind) или (None, None). kind: point|subpoint."""
    s = line.strip()
    m = RE_POINT_LINE.match(s)
    kind = "point"
    if not m:
        m = RE_SUBPOINT_LINE.match(s)
        kind = "subpoint"
    if not m:
        return None, None
    pid, rest = m.group(1), m.group(2)
    if not point_body_starts_ok(rest):
        return None, None
    prev = line_state.prev_line.rstrip()
    if line_state.prev_was_article_heading:
        return pid, kind
    if boundary_before_structure(line_state.prev_line, line_state=line_state):
        return pid, kind
    if prev and RE_REF_WORD_BEFORE_POINT.search(prev):
        return None, None
    if prev and RE_LOWERCASE_WORD_TAIL.search(prev) and prev[-1] not in ".:;!?":
        return None, None
    return None, None


def split_inline_article_segments(line: str) -> list[str]:
    """Делит строку по capital «Статья N» только после настоящего конца предложения."""
    parts: list[str] = []
    pos = 0
    for m in RE_INLINE_ARTICLE.finditer(line):
        start = m.start()
        if start == 0:
            continue
        before = line[:start]
        if not is_real_sentence_end_before(before):
            continue
        candidate = line[start:].lstrip()
        if not (
            RE_ARTICLE_HEADING_STRICT.match(candidate)
            or RE_ARTICLE_BARE.match(candidate)
        ):
            continue
        chunk = line[pos:start].strip()
        if chunk:
            parts.append(chunk)
        pos = start
    tail = line[pos:].strip()
    if tail:
        parts.append(tail)
    return parts if parts else ([line.strip()] if line.strip() else [])
