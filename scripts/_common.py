"""Общие мелочи для скриптов атомной памяти: подключение, tsquery, версия."""
import os
import re


def _version():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "VERSION")
    try:
        return open(p, encoding="utf-8").read().strip()
    except OSError:
        return "0.0.0"


__version__ = _version()

STOPWORDS = {
    "что", "как", "какие", "какой", "какая", "по", "для", "при", "это",
    "означает", "означают", "значит", "номер", "цифры", "цифра",
    "the", "and", "for", "with", "from", "this", "that", "are",
    "was", "not", "have", "been", "were", "will",
}


def get_dsn() -> str:
    """PG_DSN из окружения. Без него — ошибка, никаких паролей в коде."""
    dsn = os.environ.get("PG_DSN")
    if not dsn:
        raise SystemExit(
            "PG_DSN не задан: export PG_DSN=postgresql://user:pass@host:5432/db")
    return dsn


def normalize_table_no(target: str) -> str:
    """«Б.1» → «Б», «6» → «6» (отрезаем подномер таблицы)."""
    return (target or "").strip().split(".")[0].strip().upper()


def normalize_fig_no(target: str) -> str:
    """Каноническая форма номера рисунка: «рис. 3б» → «рис. 3», «3» → «рис. 3»."""
    t = (target or "").strip().lower()
    m = re.match(r"(?:рис\.?\s*)?(\d+)(?:[а-яa-z])?$", t)
    return f"рис. {m.group(1)}" if m else t


def ili_terms(q: str):
    """Значимые токены для ILIKE, включая числа. Общий для CLI и MCP."""
    toks = re.findall(r"[а-яёa-z0-9.-]{2,}", q.lower(), re.UNICODE)
    return [t for t in toks if t not in STOPWORDS][:4]


def fts_query(q: str):
    """Свободный запрос -> tsquery: стемы через OR, чтобы длинный вопрос
    не обнулял выдачу (AND всех слов почти ничего не находил).
    Возвращает None, если значимых слов нет (только числа/стоп-слова)."""
    words = re.findall(r"[а-яёa-z]{3,}", q.lower(), re.UNICODE)
    words = [w for w in words if w not in STOPWORDS]
    return " | ".join(words) or None


def linked_by_atom(cur, atom_ids):
    """Связанные атомы (atom_links) одним запросом для набора from_atom.

    Возвращает {from_atom: [(atom_type, content, metadata), ...]} до 3 на атом,
    вместо запроса на каждый атом (был N+1).
    """
    if not atom_ids:
        return {}
    cur.execute(
        """
        SELECT from_atom, atom_type, content, metadata FROM (
            SELECT l.from_atom, t.atom_type, t.content, t.metadata,
                   row_number() OVER (PARTITION BY l.from_atom ORDER BY t.id) rn
            FROM atom_links l JOIN atoms t ON t.id = l.to_atom
            WHERE l.from_atom = ANY(%s) AND t.status = 'active') x
        WHERE rn <= 3
        """,
        (list(atom_ids),))
    out = {}
    for from_atom, atype, content, meta in cur.fetchall():
        out.setdefault(from_atom, []).append((atype, content, meta))
    return out

