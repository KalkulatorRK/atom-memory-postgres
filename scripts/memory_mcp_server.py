#!/usr/bin/env python3
"""MCP-сервер «Память агента» — доступ к атомной БД PostgreSQL для Hermes."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import __version__

PG_DSN = os.environ.get("PG_DSN") or ""


def get_pg():
    import psycopg2

    if not PG_DSN:
        raise SystemExit("PG_DSN не задан: export PG_DSN=postgresql://user:pass@host:5432/db")
    return psycopg2.connect(PG_DSN)


def search_atoms(query: str, project: str = "", limit: int = 5, mode: str = "hybrid"):
    from search_core import hit_to_dict, search

    limit = max(1, min(int(limit), 50))
    eff_limit = min(limit, 10)
    conn = get_pg()
    sr = search(conn, query, project=project or None, limit=eff_limit, mode=mode)
    conn.close()
    return [hit_to_dict(h) for h in sr.results], sr.warnings


def mcp_include_warnings(explicit: bool | None = None) -> bool:
    """Opt-in: объект с warnings вместо массива (совместимость 1.8 по умолчанию)."""
    if explicit is not None:
        return explicit
    return os.environ.get("ATOM_MEMORY_MCP_INCLUDE_WARNINGS", "").strip() in (
        "1",
        "true",
        "yes",
    )


def format_memory_search_response(
    res: list,
    warnings: list[str],
    *,
    include_warnings: bool = False,
) -> str:
    """JSON-RPC text: по умолчанию массив хитов как в v1.8."""
    if include_warnings and warnings:
        payload: dict = {"results": res, "warnings": warnings}
        if not res:
            payload["message"] = "ничего не найдено"
        return json.dumps(payload, ensure_ascii=False)
    if res:
        return json.dumps(res, ensure_ascii=False)
    return "ничего не найдено"


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
    from embeddings import resolve_provider

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
    cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
    row = cur.fetchone()
    pgv = row[0] if row else "?"
    provider, pw = resolve_provider()
    coverage = {}
    if provider:
        space, dims = provider.space, provider.dims
        cur.execute(
            """
            SELECT count(DISTINCT e.atom_id) FROM embeddings e
            JOIN atoms a ON a.id = e.atom_id AND a.status='active'
            WHERE e.model=%s AND e.dims=%s
            """,
            (space, dims),
        )
        emb = cur.fetchone()[0]
        pct = round(100.0 * emb / atoms, 1) if atoms else 0.0
        coverage = {"space": space, "embedded": emb, "total": atoms, "pct": pct}
    cur.close()
    conn.close()
    prov_desc = "выключен"
    if provider:
        d = provider.describe()
        prov_desc = f"{d.get('kind')} ({d.get('model')})"
    elif pw:
        prov_desc = f"выключен ({pw[-1][:80]})"
    return {
        "atoms": atoms,
        "links": links,
        "versions": versions,
        "db_size": size,
        "pgvector": pgv,
        "provider": prov_desc,
        "coverage": coverage,
    }


def _format_search_results(res, warnings):
    if warnings:
        prefix = "⚠ " + "; ".join(warnings)
    else:
        prefix = ""
    if not res:
        text = "Ничего не найдено в базе знаний."
        return (prefix + "\n" + text).strip() if prefix else text
    out = []
    for r in res:
        mb = "+".join(r.get("matched_by") or [])
        head = (
            f"**{r['source']}** v{r['version']} стр.{r['page']} [{r['atom_type']}]\n"
            f"{r['content']}\nсовпадение: {mb or '?'}"
        )
        if r.get("match_note"):
            head += f"\n_{r['match_note']}_"
        if r.get("summary"):
            head += f"\n_аннотация: {r['summary']}_"
        if r.get("linked"):
            head += "\nСвязано: " + "; ".join(
                f"{lnk['type']} {lnk.get('table_no') or lnk.get('fig_no') or ''}"
                for lnk in r["linked"]
            )
        out.append(head)
    body = "\n\n---\n\n".join(out)
    return (prefix + "\n\n" + body).strip() if prefix else body


def _fallback_loop():
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
                _reply(
                    rid,
                    result={
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "memory-atom-db", "version": __version__},
                    },
                )
            elif method == "ping":
                _reply(rid, result={})
            elif method == "tools/list":
                _reply(
                    rid,
                    result={
                        "tools": [
                            {
                                "name": "memory_search",
                                "description": "поиск по базе знаний",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "query": {"type": "string"},
                                        "project": {"type": "string"},
                                        "limit": {"type": "integer"},
                                        "mode": {
                                            "type": "string",
                                            "enum": ["fts", "vector", "hybrid"],
                                            "default": "hybrid",
                                        },
                                        "include_warnings": {
                                            "type": "boolean",
                                            "default": False,
                                            "description": "если true — JSON-объект с warnings вместо массива",
                                        },
                                    },
                                },
                            }
                        ]
                    },
                )
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
                    mode = args.get("mode", "hybrid")
                    if mode not in ("fts", "vector", "hybrid"):
                        _reply(
                            rid,
                            error={
                                "code": -32602,
                                "message": "Invalid params: mode must be fts, vector, hybrid",
                            },
                        )
                        continue
                    inc_w = args.get("include_warnings")
                    if inc_w is not None and not isinstance(inc_w, bool):
                        _reply(
                            rid,
                            error={
                                "code": -32602,
                                "message": "Invalid params: include_warnings",
                            },
                        )
                        continue
                    res, warnings = search_atoms(
                        args.get("query", ""), args.get("project", ""), limit, mode
                    )
                    include_w = mcp_include_warnings(inc_w)
                    if warnings and not include_w:
                        for w in warnings:
                            sys.stderr.write(f"memory_search: {w}\n")
                    text = format_memory_search_response(
                        res, warnings, include_warnings=include_w
                    )
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
        def memory_search(
            query: str,
            project: str = "",
            limit: int = 5,
            mode: str = "hybrid",
            include_warnings: bool = False,
        ) -> str:
            """Поиск по атомной базе знаний (FTS, вектор или гибрид).

            query — текст запроса; project — имя проекта или пусто для всех;
            limit — число результатов (до 10); mode — fts | vector | hybrid;
            include_warnings — если True, вернуть JSON с полем warnings (иначе текст/массив как раньше).
            """
            try:
                res, warnings = search_atoms(query, project, min(limit, 10), mode)
                if include_warnings:
                    return format_memory_search_response(
                        res, warnings, include_warnings=True
                    )
                return _format_search_results(res, warnings)
            except Exception as e:
                return f"Ошибка поиска: {e}"

        @mcp.tool()
        def memory_sources() -> str:
            """Список источников в базе: название, проект, версия, число атомов, префикс sha256."""
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
            """Сводка БД: число атомов, связей, версий, размер, pgvector, провайдер эмбеддингов и покрытие векторами."""
            try:
                s = stats()
                lines = [
                    f"Атомов: {s['atoms']}",
                    f"Связей (atom_links): {s['links']}",
                    f"Версий: {s['versions']}",
                    f"Размер БД: {s['db_size']}",
                    f"pgvector: {s['pgvector']}",
                    f"Провайдер: {s['provider']}",
                ]
                c = s.get("coverage") or {}
                if c:
                    lines.append(
                        f"Векторы: {c.get('space')} — {c.get('embedded')} из {c.get('total')} "
                        f"({c.get('pct')}%)"
                    )
                return "\n".join(lines)
            except Exception as e:
                return f"Ошибка: {e}"

        mcp.run(transport="stdio")
    except ImportError:
        _fallback_loop()


if __name__ == "__main__":
    main()
