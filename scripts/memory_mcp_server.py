#!/usr/bin/env python3
"""MCP-сервер «Память агента» — доступ к атомной БД PostgreSQL для Hermes.

Инструменты:
  memory_search(query, project, limit)  — FTS-поиск по атомам + связанные (atom_links)
  memory_sources()                      — список документов/версий в базе
  memory_stats()                        — статистика базы

Локальный stdio MCP-сервер. Регистрация в Hermes:
  hermes config set mcp_servers.memory.command "python3"
  hermes config set mcp_servers.memory.args '["/home/hermesadm/.hermes/scripts/memory_mcp_server.py"]'
"""
import json
import os
import re
import sys

PG_DSN = os.environ.get("PG_DSN") or ""


def get_pg():
    import psycopg2
    if not PG_DSN:
        raise SystemExit("PG_DSN не задан: export PG_DSN=postgresql://user:pass@host:5432/db")
    return psycopg2.connect(PG_DSN)


def fts_query(q: str) -> str:
    """Преобразует свободный запрос в tsquery (русские стемминги + AND)."""
    words = re.findall(r"[\wа-яё-]{3,}", q.lower(), re.UNICODE)
    words = [w for w in words if w not in ("что", "как", "какие", "какой", "по", "для", "при")]
    if not words:
        return "''"
    return " & ".join(words)


def search_atoms(query: str, project: str = "", limit: int = 5):
    conn = get_pg()
    cur = conn.cursor()
    tq = fts_query(query)

    sql = """
        SELECT a.id, a.atom_type, a.content, a.metadata, a.document_id,
               s.title AS source, v.version_no,
               ts_rank(to_tsvector('ru_en', a.content), to_tsquery('ru_en', %s)) AS rank
        FROM atoms a
        JOIN versions v ON a.version_id = v.id
        JOIN sources s ON a.document_id = s.id
        JOIN projects p ON s.project_id = p.id
        WHERE a.status = 'active'
          AND to_tsvector('ru_en', a.content) @@ to_tsquery('ru_en', %s)
    """
    params = [tq, tq]
    if project:
        sql += " AND p.name ILIKE %s"
        params.append(f"%{project}%")
    sql += " ORDER BY rank DESC LIMIT %s"
    params.append(limit)

    cur.execute(sql, params)
    rows = cur.fetchall()

    results = []
    for aid, atype, content, meta, docid, source, vno, rank in rows:
        page = (meta or {}).get("page", "?")
        # Подтягиваем связанные атомы (atom_links) — таблицы/схемы по ссылкам
        linked = []
        cur.execute("""
            SELECT t.atom_type, t.content, t.metadata
            FROM atom_links l JOIN atoms t ON l.to_atom = t.id
            WHERE l.from_atom = %s AND t.status = 'active'
            LIMIT 3
        """, (aid,))
        for ttype, tcontent, tmeta in cur.fetchall():
            linked.append({
                "type": ttype,
                "content": (tcontent or "")[:300],
                "table_no": (tmeta or {}).get("table_no"),
                "fig_no": (tmeta or {}).get("fig_no"),
            })

        results.append({
            "id": aid,
            "atom_type": atype,
            "content": content[:500],
            "tags": (meta or {}).get("tags", []),
            "summary": (meta or {}).get("summary", ""),
            "page": page,
            "source": source,
            "version": vno,
            "linked": linked,
        })
    cur.close()
    conn.close()
    return results


def list_sources():
    conn = get_pg()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.title, p.name, v.version_no, v.sha256,
               (SELECT count(*) FROM atoms a WHERE a.version_id = v.id AND a.status='active')
        FROM sources s
        JOIN projects p ON s.project_id = p.id
        JOIN versions v ON v.source_id = s.id
        ORDER BY s.id
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {"source": t, "project": p, "version": v, "sha256": s[:12], "atoms": n}
        for t, p, v, s, n in rows
    ]


def stats():
    conn = get_pg()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM atoms WHERE status='active'")
    atoms = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM atom_links")
    links = cur.fetchone()[0]
    cur.execute("SELECT count(DISTINCT version_id) FROM atoms")
    versions = cur.fetchone()[0]
    cur.execute("SELECT pg_size_pretty(pg_database_size('memory'))")
    size = cur.fetchone()[0]
    cur.close()
    conn.close()
    return {"atoms": atoms, "links": links, "versions": versions, "db_size": size}


# ===== MCP-обвязка (stdio, JSON-RPC) =====

def main():
    try:
        from mcp.server.fastmcp import FastMCP
        mcp = FastMCP("memory-atom-db")

        @mcp.tool()
        def memory_search(query: str, project: str = "", limit: int = 5) -> str:
            """Поиск по атомной базе знаний (ГОСТы и документы). Возвращает атомы
            с содержимым, метаданными и связанными таблицами/схемами.
            query — вопрос по-русски («какие методы радиографического контроля»).
            project — фильтр проекта (например «my-project»), пусто = все.
            limit — сколько атомов вернуть (1-10)."""
            try:
                res = search_atoms(query, project, min(limit, 10))
                if not res:
                    return "Ничего не найдено в базе знаний."
                out = []
                for r in res:
                    head = f"**{r['source']}** v{r['version']} стр.{r['page']} [{r['atom_type']}]\n{r['content']}"
                    if r["summary"]:
                        head += f"\n_аннотация: {r['summary']}_"
                    if r["linked"]:
                        head += "\nСвязано: " + "; ".join(
                            f"{l['type']} {l.get('table_no') or l.get('fig_no') or ''}" for l in r["linked"]
                        )
                    out.append(head)
                return "\n\n---\n\n".join(out)
            except Exception as e:
                return f"Ошибка поиска: {e}"

        @mcp.tool()
        def memory_sources() -> str:
            """Список документов (ГОСТов) в базе знаний с версиями и числом атомов."""
            try:
                rows = list_sources()
                if not rows:
                    return "База знаний пуста."
                return "\n".join(
                    f"- {r['source']} ({r['project']}, v{r['version']}, {r['atoms']} атомов, {r['sha256']})"
                    for r in rows
                )
            except Exception as e:
                return f"Ошибка: {e}"

        @mcp.tool()
        def memory_stats() -> str:
            """Статистика атомной базы знаний: число атомов, связей, версий, размер БД."""
            try:
                s = stats()
                return (f"Атомов: {s['atoms']}\nСвязей (atom_links): {s['links']}\n"
                        f"Версий: {s['versions']}\nРазмер БД: {s['db_size']}")
            except Exception as e:
                return f"Ошибка: {e}"

        mcp.run(transport="stdio")
    except ImportError:
        # Fallback: без mcp-пакета — простой JSON-RPC поверх stdio
        sys.stderr.write("mcp не установлен, работаю в JSON-режиме\n")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                method = req.get("method", "")
                params = req.get("params", {})
                if method == "tools/list":
                    out = {"jsonrpc": "2.0", "id": req.get("id"),
                           "result": {"tools": [
                               {"name": "memory_search", "description": "поиск по базе знаний",
                                "inputSchema": {"type": "object", "properties": {
                                    "query": {"type": "string"}, "project": {"type": "string"},
                                    "limit": {"type": "integer"}}}},
                           ]}}
                elif method == "tools/call":
                    name = params.get("name")
                    args = params.get("arguments", {})
                    if name == "memory_search":
                        res = search_atoms(args.get("query", ""), args.get("project", ""), args.get("limit", 5))
                        text = json.dumps(res, ensure_ascii=False) if res else "ничего не найдено"
                        out = {"jsonrpc": "2.0", "id": req.get("id"),
                               "result": {"content": [{"type": "text", "text": text}]}}
                    else:
                        out = {"jsonrpc": "2.0", "id": req.get("id"),
                               "result": {"content": [{"type": "text", "text": "неизвестный инструмент"}]}}
                else:
                    out = {"jsonrpc": "2.0", "id": req.get("id"), "result": {}}
                print(json.dumps(out, ensure_ascii=False), flush=True)
            except Exception:
                pass


if __name__ == "__main__":
    main()
