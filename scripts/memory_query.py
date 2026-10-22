#!/usr/bin/env python3
"""Быстрый поиск по атомной памяти агента (PostgreSQL, БД memory).

Вызывается через триггеры «память:», «#память», «memory:» (скилл memory-query).

  ~/hermes-env/bin/python3 ~/.hermes/scripts/memory_query.py "цифры 12 в номере ИКИ"
  ~/hermes-env/bin/python3 ~/.hermes/scripts/memory_query.py "чувствительность ИКИ" --limit 8

Логика: FTS по русским стемам (как в memory_mcp_server.py); если результатов
мало — fallback ILIKE по значимым словам (включая числа: «12», «1.5»).
Вывод — компактный, для дальнейшей сборки ответа агентом.
"""
import argparse
import os
import re
import sys

import psycopg2

from _common import fts_query


def get_dsn():
    dsn = os.environ.get("PG_DSN")
    if dsn:
        return dsn
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("PG_DSN="):
                    return line.strip().split("=", 1)[1]
    raise SystemExit("PG_DSN не найден ни в окружении, ни в ~/.hermes/.env")


STOPWORDS = {
    "что", "как", "какие", "какой", "какая", "по", "для", "при", "это",
    "означает", "означают", "значит", "номер", "цифры", "цифра",
    "the", "and", "for", "with", "from", "this", "that", "are",
    "was", "not", "have", "been", "were", "will",
}


def terms_for_ili(q: str):
    """Значимые токены для ILIKE, включая числа (2+ символа)."""
    toks = re.findall(r"[а-яёa-z0-9.-]{2,}", q.lower(), re.UNICODE)
    return [t for t in toks if t not in STOPWORDS][:4]


def main():
    ap = argparse.ArgumentParser(description="Поиск по атомной памяти агента")
    ap.add_argument("query", help="поисковый запрос")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--project", default="")
    args = ap.parse_args()

    conn = psycopg2.connect(get_dsn())
    cur = conn.cursor()

    tq = fts_query(args.query)
    sql = """
        SELECT a.id, a.atom_type, a.content, a.metadata, s.title AS source,
               v.version_no,
               ts_rank(a.tsv, to_tsquery('public.ru_en', %s)) AS rank
        FROM atoms a
        JOIN versions v ON a.version_id = v.id
        JOIN sources s ON a.document_id = s.id
        WHERE a.status = 'active'
          AND a.tsv @@ to_tsquery('public.ru_en', %s)
    """
    params = [tq, tq]
    if args.project:
        sql += " AND s.project_id IN (SELECT id FROM projects WHERE name = %s)"
        params.append(args.project)
    sql += " ORDER BY rank DESC LIMIT %s"
    params.append(args.limit)

    cur.execute(sql, params)
    rows = cur.fetchall()

    if len(rows) < args.limit:
        # Добираем ILIKE-выдачей (числа FTS не ловит), но уже найденное не выбрасываем.
        seen = {r[0] for r in rows}
        terms = terms_for_ili(args.query)
        if terms:
            cond = " OR ".join(["a.content ILIKE '%%' || %s || '%%'" for _ in terms])
            cur.execute(
                """
                SELECT a.id, a.atom_type, a.content, a.metadata, s.title AS source,
                       v.version_no, 0 AS rank
                FROM atoms a
                JOIN versions v ON a.version_id = v.id
                JOIN sources s ON a.document_id = s.id
                WHERE a.status = 'active' AND (%s)
                  AND (%s = '' OR s.project_id IN (SELECT id FROM projects WHERE name = %s))
                ORDER BY a.id LIMIT %s
                """ % (cond, "%s"),
                terms + [args.project, args.project, args.limit],
            )
            for r in cur.fetchall():
                if r[0] not in seen and len(rows) < args.limit:
                    rows.append(r)

    for aid, atype, content, meta, source, vno, rank in rows:
        page = (meta or {}).get("page") or "?"
        tags = (meta or {}).get("tags", [])
        print(f"[{aid}] {source} v{vno} стр.{page} ({atype}) {content[:400]}")
        if tags:
            print(f"    теги: {', '.join(tags[:8])}")
        # Связанные атомы: таблицы/схемы по atom_links
        cur.execute(
            """
            SELECT t.atom_type, left(t.content, 200), t.metadata
            FROM atom_links l JOIN atoms t ON l.to_atom = t.id
            WHERE l.from_atom = %s AND t.status = 'active' LIMIT 3
            """,
            (aid,),
        )
        for ttype, tcontent, tmeta in cur.fetchall():
            loc = ""
            if tmeta:
                if tmeta.get("table_no"):
                    loc = f" табл.{tmeta['table_no']}"
                elif tmeta.get("fig_no"):
                    loc = f" {tmeta['fig_no']}"
            print(f"    ↳ {ttype}{loc}: {tcontent}")
        print()

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
