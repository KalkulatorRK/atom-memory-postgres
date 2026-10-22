#!/usr/bin/env python3
"""MCP-сервер «Память агента» — доступ к атомной БД PostgreSQL для Hermes.

Инструменты:
  memory_search(query, project, limit)  — FTS-поиск по атомам + связанные (atom_links)
  memory_sources()                      — список документов/версий в базе
  memory_stats()                        — статистика базы

Локальный stdio MCP-сервер. Регистрация в Hermes:
  hermes config set mcp_servers.memory.command "python3"
  hermes config set mcp_servers.memory.args '["scripts/memory_mcp_server.py"]'
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fts_query, ili_terms, __version__

PG_DSN = os.environ.get("PG_DSN") or ""


def get_pg():
    import psycopg2
    if not PG_DSN:
        raise SystemExit("PG_DSN не задан: export PG_DSN=postgresql://user:pass@host:5432/db")
    return psycopg2.connect(PG_DSN)


def search_atoms(query: str, project: str = "", limit: int = 5):
    limit = max(1, min(int(limit), 50))
    conn = get_pg()
    cur = conn.cursor()

    rows = []
    tq = fts_query(query)
    if tq:
        sql = """
            SELECT a.id, a.atom_type, a.content, a.metadata, a.document_id,
                   s.title AS source, v.version_no,
                   ts_rank(a.tsv, to_tsquery('public.ru_en', %s)) AS rank
            FROM atoms a
            JOIN versions v ON a.version_id = v.id
            JOIN sources s ON a.document_id = s.id
            JOIN projects p ON s.project_id = p.id
            WHERE a.status = 'active'
              AND a.tsv @@ to_tsquery('public.ru_en', %s)
        """
        params = [tq, tq]
        if project:
            sql += " AND p.name = %s"
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
            q = ("SELECT a.id, a.atom_type, a.content, a.metadata, a.document_id, "
                 "s.title AS source, v.version_no, 0 AS rank "
                 "FROM atoms a "
                 "JOIN versions v ON a.version_id = v.id "
                 "JOIN sources s ON a.document_id = s.id "
                 "JOIN projects p ON s.project_id = p.id "
                 "WHERE a.status = 'active' AND (" + conds + ")")
            qparams = [f"%{t}%" for t in terms]
            if project:
                q += " AND p.name = %s"
                qparams.append(project)
            q += " ORDER BY a.id LIMIT %s"
            qparams.append(limit)
            cur.execute(q, qparams)
            for r in cur.fetchall():
                if r[0] not in seen and len(rows) < limit:
                    rows.append(r)

    # Связанные атомы — одним запросом, не N+1
    from _common import linked_by_atom
    linked_map = linked_by_atom(cur, [r[0] for r in rows])
    results = []
    for aid, atype, content, meta, docid, source, vno, rank in rows:
        page = (meta or {}).get("page") or "?"
        linked = [{
            "type": ttype,
            "content": (tcontent or "")[:300],
            "table_no": (tmeta or {}).get("table_no"),
            "fig_no": (tmeta or {}).get("fig_no"),
        } for ttype, tcontent, tmeta in linked_map.get(aid, [])]

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
    cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
    size = cur.fetchone()[0]
    cur.close()
    conn.close()
    return {"atoms": atoms, "links": links, "versions": versions, "db_size": size}


# ===== MCP-обвязка (stdio, JSON-RPC) =====

def _fallback_loop():
    """JSON-RPC 2.0 поверх stdio, без пакета mcp."""
    sys.stderr.write("mcp не установлен, работаю в JSON-режиме\n")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            _reply(None, error={"code": -32700, "message": "Parse error"})
            continue
        if isinstance(req, list):
            req = None
        if not isinstance(req, dict) or req.get("jsonrpc") != "2.0" or not isinstance(req.get("method"), str):
            rid = req.get("id") if isinstance(req, dict) else None
            _reply(rid, error={"code": -32600, "message": "Invalid Request"})
            continue
        rid = req.get("id")
        method = req["method"]
        params = req.get("params", {}) or {}
        if rid is None and method.startswith("notifications/"):
            continue
        try:
            if method == "initialize":
                _reply(rid, result={"protocolVersion": "2024-11-05",
                                    "capabilities": {"tools": {}},
                                    "serverInfo": {"name": "memory-atom-db", "version": __version__}})
            elif method == "ping":
                _reply(rid, result={})
            elif method == "tools/list":
                _reply(rid, result={"tools": [
                    {"name": "memory_search", "description": "поиск по базе знаний",
                     "inputSchema": {"type": "object", "properties": {
                         "query": {"type": "string"}, "project": {"type": "string"},
                         "limit": {"type": "integer"}}}}]})
            elif method == "tools/call":
                name = params.get("name")
                args = params.get("arguments", {})
                if not isinstance(args, dict):
                    _reply(rid, error={"code": -32602, "message": "Invalid params"})
                    continue
                if name == "memory_search":
                    try:
                        limit = int(args.get("limit", 5))
                    except (TypeError, ValueError):
                        _reply(rid, error={"code": -32602, "message": "Invalid params: limit"})
                        continue
                    res = search_atoms(args.get("query", ""), args.get("project", ""), limit)
                    text = json.dumps(res, ensure_ascii=False) if res else "ничего не найдено"
                    _reply(rid, result={"content": [{"type": "text", "text": text}]})
                else:
                    _reply(rid, error={"code": -32602, "message": f"Unknown tool: {name}"})
            else:
                _reply(rid, error={"code": -32601, "message": "Method not found"})
        except Exception as e:
            sys.stderr.write(f"mcp fallback error: {type(e).__name__}: {e}\n")
            _reply(rid, error={"code": -32603, "message": "Internal error"})


def _reply(req_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    print(json.dumps(msg, ensure_ascii=False), flush=True)


def main():
    if os.environ.get("ATOM_MEMORY_MCP_FALLBACK") == "1":
        _fallback_loop()
        return
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
        _fallback_loop()


if __name__ == "__main__":
    main()
