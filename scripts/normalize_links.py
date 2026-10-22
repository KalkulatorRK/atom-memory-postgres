#!/usr/bin/env python3
"""Нормализация перекрёстных ссылок (refs → atom_links).

Стратегии сопоставления target (из текста: «6», «Б.1», «рис. 3б», «Б») с атомами:
1. Точное совпадение: table_no == target ИЛИ fig_no == target
2. Префиксное: target «Б.1» → table_no «Б»; target «рис. 3б» → fig_no «рис. 3»
3. Fallback по тексту: target «6» → атом, чей content содержит «Таблица 6»

Использование:
  python3 normalize_links.py [--version 6]
"""
import argparse
import json
import os
import re

PG_DSN = os.environ.get("PG_DSN") or ""


def get_pg():
    import psycopg2
    if not PG_DSN:
        raise SystemExit("PG_DSN не задан: export PG_DSN=postgresql://user:pass@host:5432/db")
    return psycopg2.connect(PG_DSN)


def normalize_table_no(target):
    """«Б.1» → «Б»; «6» → «6»; «Б» → «Б» (отрезаем подномер таблицы)."""
    return target.split('.')[0].strip().upper()


def normalize_fig_no(target):
    """«рис. 3б» → «рис. 3»; «рис. 3» → «рис. 3» (отрезаем подбукву рисунка)."""
    m = re.match(r'(рис\.\s*\d+)', target, re.IGNORECASE)
    return m.group(1).lower() if m else target.lower()


def resolve_links(version_no):
    conn = get_pg()
    cur = conn.cursor()

    # 1. Собираем все активные атомы версии
    cur.execute("""
        SELECT a.id, a.atom_type, a.content, a.metadata
        FROM atoms a
        JOIN versions v ON a.version_id = v.id
        WHERE v.version_no = %s AND a.status = 'active'
    """, (version_no,))
    atoms = cur.fetchall()

    # Индексы: table_no/fig_no → id (с нормализацией)
    table_idx = {}  # нормализованный table_no -> [ids]
    fig_idx = {}    # нормализованный fig_no -> [ids]
    for aid, atype, content, meta in atoms:
        meta = meta or {}
        tn = meta.get('table_no')
        fn = meta.get('fig_no')
        if tn:
            key = normalize_table_no(str(tn))
            table_idx.setdefault(key, []).append(aid)
        if fn:
            key = normalize_fig_no(str(fn))
            fig_idx.setdefault(key, []).append(aid)

    # 2. Проходим атомы с refs и резолвим
    created = 0
    for aid, atype, content, meta in atoms:
        refs = (meta or {}).get('refs', [])
        if not refs:
            continue
        for ref in refs:
            target = str(ref.get('target', '')).strip()
            rtype = str(ref.get('type', '')).lower()
            if not target:
                continue

            to_id = None
            # Стратегия 1: точное / 2: префиксное для таблиц и рисунков
            if rtype in ('table', 'appendix'):
                for cand in (target, normalize_table_no(target)):
                    if cand in table_idx and table_idx[cand]:
                        to_id = table_idx[cand][0]
                        break
            if to_id is None and rtype in ('figure', 'image'):
                for cand in (normalize_fig_no(target), target):
                    if cand in fig_idx and fig_idx[cand]:
                        to_id = fig_idx[cand][0]
                        break

            # Стратегия 3: fallback по тексту «Таблица N» / «рис. N» в content
            if to_id is None:
                pattern = None
                if rtype in ('table', 'appendix'):
                    pattern = re.compile(r'Таблица\s+' + re.escape(target.split('.')[0]) + r'[\s\-—]', re.IGNORECASE)
                elif rtype in ('figure', 'image'):
                    base = normalize_fig_no(target)
                    if base:
                        pattern = re.compile(re.escape(base), re.IGNORECASE)
                if pattern:
                    for oid, otype, ocontent, ometa in atoms:
                        if oid == aid:
                            continue
                        if pattern.search(ocontent or ''):
                            to_id = oid
                            break

            if to_id and to_id != aid:
                try:
                    cur.execute(
                        "INSERT INTO atom_links (from_atom, to_atom, rel_type) "
                        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (aid, to_id, f"references_{rtype}"))
                    if cur.rowcount > 0:
                        created += 1
                except Exception:
                    pass

    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ Нормализовано ссылок для v{version_no}: создано {created}")
    return created


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int, default=6)
    args = parser.parse_args()
    resolve_links(args.version)
