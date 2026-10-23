#!/usr/bin/env python3
"""Быстрый поиск по атомной памяти агента (PostgreSQL, БД memory).

  python3 memory_query.py "запрос" [--mode fts|vector|hybrid] [--project P] [--limit N]
"""
import argparse
import json
import os
import sys

import psycopg2

from _common import fts_query, ili_terms, linked_by_atom
from search_core import hit_to_dict, search
from structure import format_citation, normalize_date


def get_dsn_local():
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


def run_fts_legacy(cur, query: str, project: str, limit: int):
    """Поведение v1.7/v1.8: только FTS + ILIKE, тот же формат вывода."""
    rows = []
    tq = fts_query(query)
    if tq:
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
        if project:
            sql += " AND s.project_id IN (SELECT id FROM projects WHERE name = %s)"
            params.append(project)
        sql += " ORDER BY rank DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        rows = cur.fetchall()

    if len(rows) < limit:
        seen = {r[0] for r in rows}
        terms = ili_terms(query)
        if terms:
            conds = " OR ".join(["a.content ILIKE %s" for _ in terms])
            q = (
                "SELECT a.id, a.atom_type, a.content, a.metadata, s.title AS source, "
                "v.version_no, 0 AS rank "
                "FROM atoms a "
                "JOIN versions v ON a.version_id = v.id "
                "JOIN sources s ON a.document_id = s.id "
                "WHERE a.status = 'active' AND (" + conds + ")"
            )
            qparams = [f"%{t}%" for t in terms]
            if project:
                q += " AND s.project_id IN (SELECT id FROM projects WHERE name = %s)"
                qparams.append(project)
            q += " ORDER BY a.id LIMIT %s"
            qparams.append(limit)
            cur.execute(q, qparams)
            for r in cur.fetchall():
                if r[0] not in seen and len(rows) < limit:
                    rows.append(r)

    linked_map = linked_by_atom(cur, [r[0] for r in rows])
    lines = []
    for aid, atype, content, meta, source, vno, rank in rows:
        page = (meta or {}).get("page") or "?"
        tags = (meta or {}).get("tags", [])
        lines.append(f"[{aid}] {source} v{vno} стр.{page} ({atype}) {content[:400]}")
        if tags:
            lines.append(f"    теги: {', '.join(tags[:8])}")
        for ttype, tcontent, tmeta in linked_map.get(aid, []):
            loc = ""
            if tmeta:
                if tmeta.get("table_no"):
                    loc = f" табл.{tmeta['table_no']}"
                elif tmeta.get("fig_no"):
                    loc = f" {tmeta['fig_no']}"
            lines.append(f"    ↳ {ttype}{loc}: {tcontent[:200]}")
        lines.append("")
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def format_hybrid_hit(h) -> str:
    tags = (h.metadata or {}).get("tags", [])
    mb = "+".join(h.matched_by) if h.matched_by else "?"
    tail = f" [{mb}]"
    if h.match_note:
        tail += f" ({h.match_note})"
    cite = format_citation(h.metadata or {}, h.source_title)
    line = (
        f"[{h.atom_id}] {cite} v{h.version_no} "
        f"({h.atom_type}) {h.content[:400]}{tail}"
    )
    out = [line]
    if tags:
        out.append(f"    теги: {', '.join(tags[:8])}")
    for link in h.links:
        loc = link.get("table_no") or link.get("fig_no") or ""
        out.append(f"    ↳ {link.get('type')} {loc}: {(link.get('content') or '')[:200]}")
    out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Поиск по атомной памяти агента")
    ap.add_argument("query", help="поисковый запрос")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--project", default="")
    ap.add_argument("--mode", default=os.environ.get("SEARCH_MODE", "hybrid"),
                    choices=["fts", "vector", "hybrid"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--explain", action="store_true")
    ap.add_argument("--law", default="", help="фильтр metadata.law (ILIKE)")
    ap.add_argument("--doc-kind", default="", choices=["", "code", "gost", "sdank"])
    ap.add_argument("--as-of", default="", help="effective_date <= DATE (ISO или DD.MM.YYYY)")
    args = ap.parse_args()

    dsn = get_dsn_local()
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    if args.mode == "fts" and not args.json and not args.explain:
        out = run_fts_legacy(cur, args.query, args.project, args.limit)
        cur.close()
        conn.close()
        sys.stdout.write(out)
        return

    cur.close()
    as_of = normalize_date(args.as_of) if args.as_of else None
    sr = search(
        conn,
        args.query,
        project=args.project or None,
        limit=args.limit,
        mode=args.mode,
        law=args.law or None,
        doc_kind=args.doc_kind or None,
        as_of=as_of,
    )
    for w in sr.warnings:
        print(w, file=sys.stderr)

    if args.json:
        payload = {
            "results": [hit_to_dict(h) for h in sr.results],
            "warnings": sr.warnings,
            "mode_used": sr.mode_used,
            "legs": sr.legs,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        conn.close()
        return

    if not sr.results:
        print("Ничего не найдено.")
        conn.close()
        return

    if args.explain:
        print(f"mode={sr.mode_used} legs={sr.legs}", file=sys.stderr)
        for h in sr.results:
            print(
                f"  id={h.atom_id} score={h.score:.4f} ranks={h.ranks} sim={h.similarity} exact={h.exact}",
                file=sys.stderr,
            )

    for h in sr.results:
        print(format_hybrid_hit(h), end="")
    conn.close()


if __name__ == "__main__":
    main()
