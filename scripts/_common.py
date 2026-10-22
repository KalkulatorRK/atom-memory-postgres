"""Общие мелочи для скриптов атомной памяти: подключение и сборка tsquery."""
import os
import re

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


def fts_query(q: str) -> str:
    """Свободный запрос -> tsquery: стемы через OR, чтобы длинный вопрос
    не обнулял выдачу (AND всех слов почти ничего не находил)."""
    words = re.findall(r"[а-яёa-z]{3,}", q.lower(), re.UNICODE)
    words = [w for w in words if w not in STOPWORDS]
    return " | ".join(words) or "''"
