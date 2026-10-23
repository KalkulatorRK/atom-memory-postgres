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
RE_CHAPTER_HEADING = re.compile(
    r"^(?:Глава|ГЛАВА|Раздел|РАЗДЕЛ|Часть|ЧАСТЬ)\s+\S", re.IGNORECASE
)
RE_SUBSECTION_HEADING = re.compile(
    r"^(?:Подраздел|ПОДРАЗДЕЛ)\s+\S", re.IGNORECASE
)
RE_PARAGRAPH_SECTION = re.compile(r"^§\s*\d+(?:\.\d+)*\.", re.UNICODE)

BANNER_MAX_LEN = 120
RE_CONSULTANT_BANNER_START = re.compile(
    r"^(?:документ\s+предоставлен\s+)?консультант\s*плюс",
    re.IGNORECASE,
)
RE_CONSULTANT_DATE_START = re.compile(r"^дата\s+сохранения", re.IGNORECASE)
RE_CONSULTANT_SUPPORT_START = re.compile(
    r"^консультант\s*плюс\s+надежная\s+правовая\s+поддержка",
    re.IGNORECASE,
)
RE_CONSULTANT_URL_START = re.compile(r"^(?:https?://|www\.)consultant\.ru", re.IGNORECASE)
RE_GOST_NUMBERED_SECTION = re.compile(r"^\d+(?:\.\d+)*\s+\S")
RE_PAGE_COUNT_LINE = re.compile(
    r"(?i)^(?:страница|стр\.?)\s*\d+\s*(?:из|/)\s*\d+\s*$"
)
RE_STANDALONE_URL = re.compile(r"(?i)^(?:https?://|www\.)\S+$")

RE_ABBREV_BEFORE_DOT = re.compile(
    r"(?i)\b(?:п|пп|ст|ч|разд|подп|абз|§)\.\s*$"
)
RE_DATE_END = re.compile(r"\d{1,2}\.\d{1,2}\.\d{2,4}\.\s*$")

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

RE_PAREN_BOUNDARY = re.compile(
    r"^\((?:в\s*ред\.|п\.\s*\d+\s*в\s*ред\.|введен|введён|утратил|утратила)",
    re.IGNORECASE,
)
RE_FZ_WRAP_LINE = re.compile(r"^\d+\s+Федерального\s+зак", re.IGNORECASE)
RE_REPEALED_TAIL = re.compile(r"(?i)утратил")
RE_REPEALED_HEADING_END = re.compile(r"(?i)утратил(?:ла|ли)?\s+силу\.?\s*$")
RE_REPEALED_HEADING_START = re.compile(
    r"^(?:Статья|СТАТЬЯ|Статьи|СТАТЬИ)\s+\d"
)
RE_ARTICLES_RANGE = re.compile(
    r"(?i)статьи\s+(\d+(?:\.\d+)*)\s*[-–—]\s*(\d+(?:\.\d+)*)"
)
RE_ARTICLE_NUM_IN_LINE = re.compile(
    r"(?i)(?:статьи|статья|СТАТЬЯ)\s+(\d+(?:\.\d+)*)"
)
RE_CHAPTER_NUMBER = re.compile(
    r"^(?:Глава|ГЛАВА)\s+(\d+(?:\.\d+)*)",
    re.IGNORECASE,
)
CODE_VOLUME_HEADING_MAX = 220
RE_STRICT_CHAPTER = re.compile(r"^Глава\s+(\d+(?:\.\d+)*)\.\s+\S")
RE_STRICT_SECTION = re.compile(r"^Раздел\s+([IVXLCDM\d]+)\.\s+\S")
RE_STRICT_SUBSECTION = re.compile(r"^Подраздел\s+\S")
RE_STRICT_PARAGRAPH = re.compile(r"^§\s*(\d+(?:\.\d+)*)\.\s+\S")


@dataclass
class ArticleHeadingState:
    last_article: tuple[int, ...] | None = None
    lowercase_headings: bool = False
    after_toc_restart: bool = False
    in_toc_run: bool = False
    consecutive_heading_lines: int = 0
    false_forward_anchor: tuple[int, ...] | None = None
    false_forward_spurious: tuple[int, ...] | None = None
    allow_large_forward: bool = False
    chapter_article_prefix: tuple[int, ...] | None = None
    saw_substantive_body: bool = False


@dataclass
class StructureLineState:
    """Состояние между строками/абзацами (границы + оглавление)."""

    prev_line: str = ""
    at_doc_start: bool = True
    after_page_break: bool = False
    preserve_page_break: bool = False
    heading: ArticleHeadingState = field(default_factory=ArticleHeadingState)
    prev_was_structure_heading: bool = False
    prev_list_style: str | None = None


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


def is_repealed_range_heading_line(s: str) -> bool:
    """Заголовок-якорь: строка целиком «Статья/Статьи N… … утратили силу»."""
    s = s.strip()
    if not s or not RE_REPEALED_HEADING_START.match(s):
        return False
    if not RE_REPEALED_HEADING_END.search(s):
        return False
    return not is_repealed_article_heading(s)


def is_strict_code_chapter_heading(s: str) -> bool:
    s = s.strip()
    return len(s) <= CODE_VOLUME_HEADING_MAX and bool(RE_STRICT_CHAPTER.match(s))


def is_strict_code_section_heading(s: str) -> bool:
    s = s.strip()
    return len(s) <= CODE_VOLUME_HEADING_MAX and bool(RE_STRICT_SECTION.match(s))


def is_strict_code_subsection_heading(s: str) -> bool:
    s = s.strip()
    return len(s) <= CODE_VOLUME_HEADING_MAX and bool(RE_STRICT_SUBSECTION.match(s))


def is_strict_code_paragraph_heading(s: str) -> bool:
    s = s.strip()
    return len(s) <= CODE_VOLUME_HEADING_MAX and bool(RE_STRICT_PARAGRAPH.match(s))


def is_strict_code_volume_heading(s: str) -> bool:
    return (
        is_strict_code_chapter_heading(s)
        or is_strict_code_section_heading(s)
        or is_strict_code_subsection_heading(s)
        or is_strict_code_paragraph_heading(s)
    )


def chapter_heading_article_prefix(s: str) -> tuple[int, ...] | None:
    m = RE_STRICT_CHAPTER.match(s.strip())
    if not m:
        return None
    return article_number_tuple(m.group(1))


def _reset_article_numbering(hs: ArticleHeadingState) -> None:
    hs.last_article = None
    hs.false_forward_anchor = None
    hs.false_forward_spurious = None


def _begin_chapter_heading(hs: ArticleHeadingState, line: str) -> None:
    _reset_article_numbering(hs)
    hs.chapter_article_prefix = chapter_heading_article_prefix(line)


def _begin_code_section_heading(hs: ArticleHeadingState) -> None:
    _reset_article_numbering(hs)
    hs.chapter_article_prefix = None


def _under_chapter_prefix(
    state: ArticleHeadingState, num: tuple[int, ...]
) -> bool:
    p = state.chapter_article_prefix
    if not p or len(num) <= len(p):
        return False
    return num[: len(p)] == p


def repealed_range_anchor(s: str) -> tuple[int, ...] | None:
    """Последний номер в строке «Статьи N–M … утратили силу» / перечне статей."""
    s = s.strip()
    if not is_repealed_range_heading_line(s):
        return None
    m = RE_ARTICLES_RANGE.search(s)
    if m:
        return article_number_tuple(m.group(2))
    nums: list[tuple[int, ...]] = []
    for m in RE_ARTICLE_NUM_IN_LINE.finditer(s):
        t = article_number_tuple(m.group(1))
        if t:
            nums.append(t)
    return max(nums) if nums else None


def _successor_article(
    base: tuple[int, ...], candidate: tuple[int, ...]
) -> bool:
    """Следующая статья: K+1, K.1 или K.n+1 на том же уровне."""
    if candidate <= base:
        return False
    if len(base) == 1 and len(candidate) == 1 and candidate[0] == base[0] + 1:
        return True
    if len(candidate) == len(base) + 1 and candidate[:-1] == base and candidate[-1] == 1:
        return True
    if (
        len(candidate) == len(base)
        and candidate[:-1] == base[:-1]
        and candidate[-1] == base[-1] + 1
    ):
        return True
    return False


def is_capital_article_heading(s: str) -> bool:
    return bool(
        RE_ARTICLE_HEADING_STRICT.match(s)
        or RE_ARTICLE_BARE.match(s)
    )


def is_article_heading_line(s: str) -> bool:
    s = s.strip()
    return bool(
        RE_ARTICLE_HEADING_STRICT.match(s)
        or RE_ARTICLE_BARE.match(s)
    )


def is_structure_heading_line(s: str) -> bool:
    s = s.strip()
    return bool(
        is_article_heading_line(s)
        or is_strict_code_volume_heading(s)
        or re.match(r"^(?:Часть|ЧАСТЬ)\s+\S", s, re.IGNORECASE)
    )


def is_code_structure_boundary_line(s: str) -> bool:
    """Граница блока в кодексе: глава / § / раздел (не склеивать в normalize)."""
    s = s.strip()
    return is_strict_code_volume_heading(s)


RE_FZ_RUNNING_HEADER = re.compile(
    r"(?i)^(?:"
    r"Федеральный\s+закон\s+от\s+\d{2}\.\d{2}\.\d{4}\s+N\s+\d+(?:\.\d+)?-ФЗ"
    r"|(?:Постановлени[ея]|Указ)\s+"
    r"|(?:ГОСТ(?:\s*Р)?|ISO)\s+[\d][\d.\w\-]*"
    r"|\"?(?:Конституция|Гражданский\s+кодекс|Налоговый\s+кодекс)"
    r")"
)


def is_consultant_header_wrap_fragment(s: str) -> bool:
    """Продолжение 2–3-строчного колонтитула ФЗ (перенос названия закона)."""
    s = s.strip()
    if not s or len(s) > 200 or RE_POINT_LINE.match(s):
        return False
    if re.match(r"^[«\"(]", s) and re.search(r"(?i)федеральн", s):
        return True
    if (
        re.match(r"^[а-яё]", s)
        and re.search(r'"\s*$', s)
        and len(s.split()) <= 28
    ):
        return True
    return False


def is_consultant_running_header_prefix(s: str) -> bool:
    """Колонтитул КонсультантПлюс / повторяющаяся шапка страницы (не тело статьи)."""
    s = s.strip()
    if not s or len(s) > 240:
        return False
    if is_consultant_header_wrap_fragment(s):
        return True
    if len(s) < 8:
        return False
    if re.search(r"(?i)кодекс", s) and re.match(
        r'(?i)^(?:\"[^\"]+\"\s+|[^\n]{0,100}?(?:кодекс\b))[^\n]{0,40}\bглава\s+\d+\.',
        s,
    ):
        return True
    if RE_FZ_RUNNING_HEADER.match(s):
        return True
    if re.search(r"(?i)консультант\s*плюс", s):
        return True
    return False


def is_running_header_line(s: str, *, repeated: bool = False) -> bool:
    s = s.strip()
    if not s or s.startswith("<!--"):
        return False
    if is_consultant_running_header_prefix(s):
        return True
    if len(s) > BANNER_MAX_LEN:
        return False
    if repeated and is_strict_code_volume_heading(s):
        return True
    if RE_GOST_NUMBERED_SECTION.match(s):
        return False
    if (
        RE_CONSULTANT_BANNER_START.match(s)
        or RE_CONSULTANT_DATE_START.match(s)
        or RE_CONSULTANT_SUPPORT_START.match(s)
        or RE_CONSULTANT_URL_START.match(s)
    ):
        return True
    if RE_PAGE_COUNT_LINE.match(s):
        return True
    if RE_STANDALONE_URL.match(s):
        return True
    if repeated and len(s) >= 12 and not is_article_heading_line(s):
        if RE_POINT_LINE.match(s) or RE_SUBPOINT_LINE.match(s):
            return False
        return True
    return False


def is_paren_boundary_line(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    if RE_PAREN_BOUNDARY.match(s):
        return True
    return s.startswith("(") and s.endswith(")")


def block_started_with_structure_heading(buffer_first: str) -> bool:
    first = buffer_first.strip()
    return bool(
        is_structure_heading_line(first)
        or re.match(r"^(?:Статья|СТАТЬЯ)\s+\d", first)
    )


def is_repealed_article_heading(s: str) -> bool:
    s = s.strip()
    return bool(is_article_heading_line(s) and re.search(r"(?i)утратил[аи]?\s+силу", s))


def counts_toward_toc_run(s: str) -> bool:
    """2+ подряд заголовков с названием (P2); не голая «Статья N» / не «Утратила силу» (Q4)."""
    s = s.strip()
    if not is_article_heading_line(s):
        return False
    if is_repealed_article_heading(s) or RE_ARTICLE_BARE.match(s):
        return False
    return True


def is_real_sentence_end_before(text: str) -> bool:
    """Конец предложения/абзаца перед кандидатом в заголовок (не «п. 3.»)."""
    before = text.rstrip()
    if not before:
        return False
    if before[-1] not in ".:;!?)":
        return False
    if before[-1] == ".":
        if RE_DATE_END.search(before):
            return True
        if RE_ABBREV_BEFORE_DOT.search(before):
            return False
    return True


def normalize_prev_for_point(buffer: list[str], prev_raw: str) -> tuple[str, bool]:
    """Контекст блока для решения «N.» в normalize_text (Q1)."""
    if not buffer:
        return prev_raw, is_structure_heading_line(prev_raw)
    joined = " ".join(buffer)
    if block_started_with_structure_heading(buffer[0]):
        if not is_real_sentence_end_before(joined):
            return joined, True
    return buffer[-1], is_structure_heading_line(buffer[-1])


def boundary_before_structure(prev_line: str, *, line_state: StructureLineState) -> bool:
    """Заголовок/пункт допустим только после границы (N1/N2)."""
    if line_state.after_page_break:
        return True
    pl = prev_line.strip()
    if is_consultant_running_header_prefix(pl) or is_consultant_header_wrap_fragment(pl):
        return True
    if line_state.at_doc_start:
        return True
    if line_state.heading.after_toc_restart:
        return True
    if not prev_line.strip():
        return False
    if line_state.prev_was_structure_heading:
        return True
    if is_paren_boundary_line(prev_line):
        return True
    return is_real_sentence_end_before(prev_line)


def is_toc_heading_line(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    if RE_TOC_TRAIL.search(s):
        return True
    if is_article_heading_line(s):
        if RE_ARTICLE_BARE.match(s):
            return False
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
    if is_article_heading_line(s):
        return False
    if RE_POINT_LINE.match(s) and len(s) > 20:
        return True
    if RE_SUBPOINT_LINE.match(s) and len(s) > 20:
        return True
    if re.match(r"^(?:Глава|Раздел|Часть)\s", s, re.IGNORECASE):
        return False
    return len(s) > 30


def _heading_article_num(s: str) -> tuple[int, ...] | None:
    m = RE_ARTICLE_HEADING_STRICT.match(s.strip()) or RE_ARTICLE_BARE.match(s.strip())
    if not m:
        return None
    return article_number_tuple(m.group(1))


def update_toc_state(
    line_state: StructureLineState,
    line: str,
    *,
    skip_volume_reset: bool = False,
) -> None:
    """TOC = 2+ подряд заголовков без тела; тело — рестарт N ≤ last (P2/Q4)."""
    s = line.strip()
    hs = line_state.heading
    if line_state.after_page_break:
        hs.in_toc_run = False
        hs.after_toc_restart = True
        if not is_strict_code_chapter_heading(s):
            _reset_article_numbering(hs)
            hs.chapter_article_prefix = None
    if is_paren_boundary_line(s):
        return
    if is_strict_code_chapter_heading(s) and not skip_volume_reset:
        if (
            not hs.in_toc_run
            or hs.last_article is not None
            or hs.after_toc_restart
            or line_state.after_page_break
        ):
            _begin_chapter_heading(hs, s)
        if not hs.in_toc_run:
            hs.consecutive_heading_lines = 0
        return
    if (
        not skip_volume_reset
        and (
            is_strict_code_section_heading(s)
            or is_strict_code_subsection_heading(s)
            or is_strict_code_paragraph_heading(s)
        )
    ):
        if (
            not hs.in_toc_run
            or hs.last_article is not None
            or hs.after_toc_restart
            or line_state.after_page_break
        ):
            _begin_code_section_heading(hs)
        if not hs.in_toc_run:
            hs.consecutive_heading_lines = 0
        return
    anchor = repealed_range_anchor(s)
    if anchor is not None:
        hs.last_article = anchor
    if is_repealed_article_heading(s):
        if hs.in_toc_run:
            return
        hs.consecutive_heading_lines = 0
        hs.in_toc_run = False
        return
    if counts_toward_toc_run(s):
        num = _heading_article_num(s)
        if hs.in_toc_run and num and hs.last_article and num < hs.last_article:
            hs.after_toc_restart = True
            hs.in_toc_run = False
            hs.consecutive_heading_lines = 0
        elif not hs.in_toc_run:
            hs.consecutive_heading_lines += 1
            if hs.consecutive_heading_lines >= 2:
                hs.in_toc_run = True
        return
    if is_substantive_body_line(s):
        if not hs.in_toc_run:
            hs.saw_substantive_body = True
        if hs.in_toc_run:
            hs.after_toc_restart = True
            hs.in_toc_run = False
        hs.consecutive_heading_lines = 0
        return
    if is_article_heading_line(s):
        num = _heading_article_num(s)
        if hs.in_toc_run and num and hs.last_article and num < hs.last_article:
            hs.after_toc_restart = True
        hs.in_toc_run = False
        hs.consecutive_heading_lines = 0
        return
    hs.consecutive_heading_lines = 0


def _likely_false_forward_heading(
    s: str,
    num: tuple[int, ...],
    last: tuple[int, ...],
    *,
    allow_large_forward: bool = False,
    prev_line: str = "",
) -> bool:
    """Только fwd_swallow: голая «Статья N» (+5) или цитата после «…содержания:»."""
    if allow_large_forward:
        return False
    if len(num) != 1 or len(last) != 1 or num[0] - last[0] < 5:
        return False
    if RE_ARTICLE_BARE.match(s):
        return True
    pl = prev_line.strip().lower()
    if (
        RE_ARTICLE_HEADING_STRICT.match(s)
        and ("содержания" in pl or pl.endswith(":"))
    ):
        return True
    return False


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

    toc_style = is_toc_heading_line(s)
    num = article_number_tuple(num_s)
    under_chapter = num is not None and _under_chapter_prefix(state, num)
    forward = (
        not lowercase
        and num is not None
        and (
            state.last_article is None
            or num > state.last_article
            or under_chapter
        )
    )
    needs_boundary = lowercase or (
        num is not None
        and state.last_article is not None
        and not (num > state.last_article)
    )
    if (
        forward
        and state.last_article is not None
        and num is not None
        and _likely_false_forward_heading(
            s,
            num,
            state.last_article,
            allow_large_forward=state.allow_large_forward,
            prev_line=line_state.prev_line,
        )
    ):
        state.false_forward_anchor = state.last_article
        state.false_forward_spurious = num
        return None, None

    if (
        state.false_forward_anchor is not None
        and num is not None
        and _successor_article(state.false_forward_anchor, num)
    ):
        state.false_forward_spurious = None
        state.false_forward_anchor = None

    if needs_boundary and not toc_style and not forward:
        if not boundary_before_structure(
            line_state.prev_line, line_state=line_state
        ):
            return None, None

    recover = (
        state.false_forward_spurious is not None
        and state.false_forward_anchor is not None
        and num is not None
        and state.false_forward_anchor < num < state.false_forward_spurious
    )
    allow_restart = (
        (state.after_toc_restart and not lowercase)
        or recover
        or under_chapter
    )
    if num is None or not _accept_monotonic(
        state, num, lowercase=lowercase, allow_restart=allow_restart
    ):
        return None, None

    if recover:
        state.false_forward_spurious = None
        state.false_forward_anchor = None

    if toc_style and not state.in_toc_run:
        return None, None

    state.last_article = num
    state.false_forward_spurious = None
    state.false_forward_anchor = None
    if state.allow_large_forward:
        state.allow_large_forward = False
    if allow_restart:
        state.after_toc_restart = False
    tail = s.split(None, 2)
    title = tail[2] if len(tail) > 2 else ""
    return num_s, title


def point_body_starts_ok(rest: str, prev_line: str) -> bool:
    if not rest:
        return False
    if re.match(r"^[A-ZА-ЯЁ«\"(0-9]", rest):
        return True
    pl = prev_line.rstrip()
    if rest[0].islower():
        if pl.endswith(":") or pl.endswith(";"):
            return True
        if RE_POINT_LINE.match(pl) or RE_SUBPOINT_LINE.match(pl):
            return True
    return False


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
    prev = line_state.prev_line
    prev_r = prev.rstrip()
    if is_consultant_running_header_prefix(prev_r) or is_consultant_header_wrap_fragment(
        prev_r
    ):
        if kind == "point" and pid.isdigit() and int(pid) <= 9:
            return pid, kind
        return None, None
    if not point_body_starts_ok(rest, prev):
        return None, None
    if kind == "subpoint":
        if is_article_heading_line(prev_r):
            line_state.prev_list_style = "paren_point"
            return pid, "point"
        if line_state.prev_list_style == "dot_point":
            line_state.prev_list_style = "paren_sub"
            return pid, kind
        if line_state.prev_list_style == "paren_point":
            prev_sub = RE_SUBPOINT_LINE.match(prev_r)
            if (
                prev_sub
                and prev_sub.group(1).isdigit()
                and pid.isdigit()
                and int(pid) == int(prev_sub.group(1)) + 1
            ):
                line_state.prev_list_style = "paren_point"
                return pid, "point"
    if line_state.prev_was_structure_heading:
        return pid, kind
    if RE_POINT_LINE.match(prev_r):
        prev_pid = RE_POINT_LINE.match(prev_r).group(1)
        if (
            prev_pid.isdigit()
            and pid.isdigit()
            and "." not in prev_pid
            and "." not in pid
            and int(pid) == int(prev_pid) + 1
        ):
            return pid, kind
    if boundary_before_structure(prev, line_state=line_state):
        return pid, kind
    if prev_r and RE_REF_WORD_BEFORE_POINT.search(prev_r):
        return None, None
    if prev_r and RE_LOWERCASE_WORD_TAIL.search(prev_r) and prev_r[-1] not in ".:;!?":
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
