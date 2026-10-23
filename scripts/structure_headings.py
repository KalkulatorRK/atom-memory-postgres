"""Проверка, что «Статья N» — заголовок, а не ссылка или перенос PDF."""
from __future__ import annotations

import re
from dataclasses import dataclass

# Заголовок: «Статья 12. Название» или «Статья 12 — Название» (не «…12 настоящего Кодекса»).
RE_ARTICLE_HEADING_STRICT = re.compile(
    r"^(?:Статья|СТАТЬЯ)\s+(\d+(?:\.\d+)?)"
    r"(?:\.\s+[0-9A-ZА-ЯЁ«\"(]|(?:\s*[—–-]\s*[0-9A-ZА-ЯЁ«\"(]))"
)
RE_ARTICLE_REFERENCE = re.compile(
    r"^(?:Статья|СТАТЬЯ|статья)\s+(\d+(?:\.\d+)?)\s+"
    r"(?:настоящего|данного|этого|указанного|вышеупомянутого|кодекса)\b",
    re.IGNORECASE,
)
RE_ARTICLE_LOW_HEADING = re.compile(
    r"^статья\s+(\d+(?:\.\d+)?)\.\s+[A-ZА-ЯЁ«\"(]"
)
RE_INLINE_ARTICLE = re.compile(r"(?:Статья|СТАТЬЯ)\s+(\d+(?:\.\d+)?)")

RE_ABBREV_BEFORE_DOT = re.compile(
    r"(?i)\b(?:п|пп|ст|ч|разд|подп|абз|§|\d+)\.\s*$"
)


@dataclass
class ArticleHeadingState:
    last_article: float | None = None
    lowercase_headings: bool = False


def detect_lowercase_heading_style(text: str) -> bool:
    lower = upper = 0
    for line in text.split("\n"):
        s = line.strip()
        if RE_ARTICLE_LOW_HEADING.match(s):
            lower += 1
        elif RE_ARTICLE_HEADING_STRICT.match(s):
            upper += 1
    return lower >= 2 and lower > upper


def _article_num(raw: str) -> float | None:
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def _monotonic_increase(state: ArticleHeadingState, num: float) -> bool:
    if state.last_article is None:
        return True
    return num > state.last_article


def is_real_sentence_end_before(text: str) -> bool:
    """Точка перед «Статья» — конец предложения, а не «п. 3.» / «ст. 475.»."""
    before = text.rstrip()
    if not before:
        return True
    if before[-1] not in ".!?":
        return False
    if RE_ABBREV_BEFORE_DOT.search(before):
        return False
    return True


def accept_article_heading(
    line: str,
    state: ArticleHeadingState,
    *,
    doc_kind: str | None,
    prev_line: str = "",
) -> tuple[str | None, str | None]:
    """Если строка — заголовок статьи, вернуть (номер, хвост); иначе (None, None)."""
    if doc_kind in ("gost", "sdank"):
        return None, None
    s = line.strip()
    if not s or RE_ARTICLE_REFERENCE.match(s):
        return None, None

    num_s: str | None = None
    if RE_ARTICLE_HEADING_STRICT.match(s):
        num_s = RE_ARTICLE_HEADING_STRICT.match(s).group(1)
    elif (
        doc_kind == "code"
        and state.lowercase_headings
        and RE_ARTICLE_LOW_HEADING.match(s)
    ):
        if prev_line and not is_real_sentence_end_before(prev_line):
            return None, None
        num_s = RE_ARTICLE_LOW_HEADING.match(s).group(1)

    if not num_s:
        return None, None

    num = _article_num(num_s)
    if num is None or not _monotonic_increase(state, num):
        return None, None

    state.last_article = num
    tail = s.split(None, 2)
    title = tail[2] if len(tail) > 2 else ""
    return num_s, title


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
        if not RE_ARTICLE_HEADING_STRICT.match(candidate):
            continue
        chunk = line[pos:start].strip()
        if chunk:
            parts.append(chunk)
        pos = start
    tail = line[pos:].strip()
    if tail:
        parts.append(tail)
    return parts if parts else ([line.strip()] if line.strip() else [])
