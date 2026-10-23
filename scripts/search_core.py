"""Гибридный поиск: FTS + ILIKE + vector, слияние RRF."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from psycopg2.extras import RealDictCursor

from _common import fts_query, ili_terms, linked_by_atom
from embeddings import (
    EmbeddingProvider,
    log_provider_once,
    min_similarity_for_space,
    resolve_provider,
)
from structure import format_citation, law_ilike_pattern, parse_date_strict

SEARCH_LEG_K = int(os.environ.get("SEARCH_LEG_K", "50"))
SEARCH_RRF_K = int(os.environ.get("SEARCH_RRF_K", "60"))
SEARCH_W_FTS = float(os.environ.get("SEARCH_W_FTS", "1.0"))
SEARCH_W_VEC = float(os.environ.get("SEARCH_W_VEC", "1.0"))
SEARCH_W_ILIKE = float(os.environ.get("SEARCH_W_ILIKE", "0.5"))
SEARCH_EXACT_MAX = int(os.environ.get("SEARCH_EXACT_MAX", "20000"))
EMBED_EF_SEARCH = int(os.environ.get("EMBED_EF_SEARCH", "100"))


@dataclass
class Hit:
    atom_id: int
    content: str
    atom_type: str
    metadata: dict
    source_title: str
    project: str
    version_no: int
    matched_by: list[str] = field(default_factory=list)
    ranks: dict[str, int] = field(default_factory=dict)
    score: float = 0.0
    similarity: float | None = None
    exact: bool = False
    match_note: str | None = None
    duplicates: int = 0
    links: list[dict] = field(default_factory=list)


@dataclass
class SearchResult:
    results: list[Hit]
    warnings: list[str]
    mode_used: str
    legs: dict[str, int]


@dataclass
class StructuredQuery:
    standard: str | None = None
    article: str | None = None
    point: str | None = None
    section: str | None = None
    annex: str | None = None


def parse_structured_query(query: str) -> StructuredQuery:
    sq = StructuredQuery()
    working = query
    m_std = re.search(
        r"(?:ГОСТ(?:\s*Р)?|СДАНК|СТО|ISO)\s*[-\w.]+", working, re.IGNORECASE
    )
    if m_std:
        sq.standard = m_std.group(0).strip()
        working = working[: m_std.start()] + " " + working[m_std.end() :]
    for m in re.finditer(
        r"(?<![\wа-яё])(?:ст\.|стать[яиюе])\s*(\d+(?:\.\d+)*)",
        working,
        re.IGNORECASE,
    ):
        sq.article = m.group(1)
    for m in re.finditer(r"(?:п|пп)\.\s*(\d+(?:\.\d+)*)", working, re.IGNORECASE):
        val = m.group(1)
        if "." in val:
            sq.section = val
        else:
            sq.point = val
    m_ann = re.search(r"(?i)приложени[ея]\s+([А-ЯA-Z])", working)
    if m_ann:
        sq.annex = m_ann.group(1).upper()
    if not sq.section and not sq.article and not sq.point:
        for m in re.finditer(r"\b(\d+(?:\.\d+){1,4})\b", working):
            sq.section = m.group(1)
            break
    return sq


def extract_identifiers(query: str) -> list[tuple[str, str]]:
    """(type, value) — тип для яруса точных совпадений."""
    out: list[tuple[str, str]] = []
    for m in re.finditer(
        r"(?:ГОСТ(?:\s*Р)?|СДАНК|СТО|ISO)\s*[-\w.]+", query, re.IGNORECASE
    ):
        out.append(("standard", m.group(0).strip()))
    for m in re.finditer(
        r"(?:ст\.?|стать[яиюе])\s*\d+(?:\.\d+)*", query, re.IGNORECASE
    ):
        out.append(("article", m.group(0).strip()))
    for m in re.finditer(r"(?:п|пп)\.\s*\d+(?:\.\d+)*", query, re.IGNORECASE):
        out.append(("point", m.group(0).strip()))
    for m in re.finditer(r"\b\d+(?:\.\d+){1,4}\b", query):
        out.append(("section", m.group(0)))
    for m in re.finditer(r"\b\w*\d\w*\b", query, re.UNICODE):
        val = m.group(0)
        if len(val) < 1:
            continue
        out.append(("token", val))
    return out


def _meta_section_matches(meta: dict, section_id: str) -> bool:
    sp = meta.get("section_path")
    if not sp:
        return False
    if isinstance(sp, list):
        if not sp:
            return False
        leaf = str(sp[-1])
        if leaf == section_id:
            return True
        if "." in section_id:
            return leaf == section_id or leaf.startswith(section_id + ".")
        if len(sp) == 1 and sp[0] == section_id:
            return True
        return False
    return str(sp) == section_id


def _meta_point_matches(meta: dict, point_id: str) -> bool:
    if str(meta.get("point") or "") == point_id:
        return True
    sp = meta.get("section_path")
    if isinstance(sp, list) and sp:
        if len(sp) == 1 and str(sp[0]) == point_id:
            return True
        leaf = str(sp[-1])
        if leaf == point_id and "." not in leaf:
            return True
    return False


def _exact_match_structured(meta: dict, sq: StructuredQuery) -> bool:
    meta = meta or {}
    if sq.article and str(meta.get("article")) != sq.article:
        return False
    if sq.point and not _meta_point_matches(meta, sq.point):
        return False
    if sq.section and not _meta_section_matches(meta, sq.section):
        return False
    if sq.annex and str(meta.get("annex") or "").upper() != sq.annex:
        return False
    if sq.standard:
        blob = " ".join(
            str(meta.get(k) or "")
            for k in ("standard", "law", "source_doc")
        ).lower()
        if sq.standard.lower() not in blob:
            return False
        if not (sq.article or sq.point or sq.section or sq.annex):
            return False
    if sq.annex or sq.article or sq.point or sq.section:
        return True
    return False


def _exact_match(content: str, meta: dict, sq: StructuredQuery) -> bool:
    if _exact_match_structured(meta, sq):
        return True
    return False


def _atom_status_sql(include_superseded: bool, as_of: str | None) -> str:
    if include_superseded or as_of:
        return ""
    return " AND a.status = 'active'"


def leg_metadata_ids(
    cur,
    sq: StructuredQuery,
    project: str | None,
    leg_k: int,
    include_superseded: bool,
    meta_sql: str,
    meta_params: list,
    as_of: str | None = None,
) -> list[int]:
    if not any((sq.standard, sq.article, sq.point, sq.section, sq.annex)):
        return []
    pf, pp = _project_filter(project)
    status = _atom_status_sql(include_superseded, as_of)
    conds: list[str] = []
    params: list = []
    if sq.article:
        conds.append("a.metadata->>'article' = %s")
        params.append(sq.article)
    if sq.point:
        conds.append(
            "(a.metadata->>'point' = %s OR a.metadata->'section_path' = %s::jsonb "
            "OR a.metadata->'section_path'->>-1 = %s)"
        )
        params.extend([sq.point, json.dumps([sq.point]), sq.point])
    if sq.section:
        conds.append(
            "(a.metadata->'section_path'->>-1 = %s "
            "OR a.metadata->'section_path'->>-1 LIKE %s)"
        )
        params.extend([sq.section, sq.section + ".%"])
    if sq.annex:
        conds.append("upper(a.metadata->>'annex') = %s")
        params.append(sq.annex.upper())
    if sq.standard:
        conds.append(
            "(a.metadata->>'standard' ILIKE %s OR a.metadata->>'law' ILIKE %s OR s.title ILIKE %s)"
        )
        like = f"%{sq.standard.split()[0]}%"
        params.extend([like, like, like])
    if not conds:
        return []
    sql = f"""
        SELECT a.id FROM atoms a
        JOIN versions v ON a.version_id = v.id
        JOIN sources s ON a.document_id = s.id
        WHERE ({' AND '.join(conds)}){status}{pf}{meta_sql}
        ORDER BY a.id LIMIT %s
    """
    cur.execute(sql, params + pp + list(meta_params) + [leg_k])
    return [r[0] for r in cur.fetchall()]


def rrf_score(ranks: dict[str, int], weights: dict[str, float], k: int = SEARCH_RRF_K) -> float:
    s = 0.0
    for leg, rank in ranks.items():
        w = weights.get(leg, 1.0)
        s += w / (k + rank)
    return s


def _project_filter(project: str | None) -> tuple[str, list]:
    if project:
        return " AND s.project_id IN (SELECT id FROM projects WHERE name = %s)", [project]
    return "", []


def _resolve_as_of(as_of: str | None, warnings: list[str]) -> str | None:
    if not as_of:
        return None
    d = parse_date_strict(as_of)
    if not d:
        warnings.append(f"фильтр --as-of игнорирован: неверная дата «{as_of}»")
        return None
    return d.isoformat()


def _metadata_filters(
    *,
    law: str | None = None,
    doc_kind: str | None = None,
    as_of: str | None = None,
) -> tuple[str, list]:
    parts: list[str] = []
    params: list = []
    lp = law_ilike_pattern(law)
    if lp:
        parts.append(
            " AND (a.metadata->>'law' ILIKE %s OR a.metadata->>'standard' ILIKE %s)"
        )
        params.extend([lp, lp])
    if doc_kind:
        parts.append(" AND a.metadata->>'doc_kind' = %s")
        params.append(doc_kind)
    if as_of:
        parts.append(
            """
            AND (
              (
                NOT EXISTS (
                  SELECT 1 FROM versions vx
                  JOIN atoms ax ON ax.version_id = vx.id
                  WHERE vx.source_id = s.id
                    AND COALESCE(ax.metadata->>'effective_date', '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                )
                AND a.status = 'active'
              )
              OR v.id = (
                SELECT v2.id FROM versions v2
                WHERE v2.source_id = s.id
                  AND EXISTS (
                    SELECT 1 FROM atoms a2
                    WHERE a2.version_id = v2.id
                      AND (a2.metadata->>'effective_date') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                      AND (a2.metadata->>'effective_date')::date <= %s::date
                  )
                ORDER BY (
                  SELECT max((a3.metadata->>'effective_date')::date)
                  FROM atoms a3
                  WHERE a3.version_id = v2.id
                    AND (a3.metadata->>'effective_date') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                ) DESC NULLS LAST, v2.version_no DESC
                LIMIT 1
              )
            )
            """
        )
        params.append(as_of)
    return "".join(parts), params


def _fetch_base_row(cur, atom_id: int) -> dict | None:
    cur.execute(
        """
        SELECT a.id, a.atom_type, a.content, a.metadata, s.title AS source_title,
               p.name AS project, v.version_no
        FROM atoms a
        JOIN versions v ON v.id = a.version_id
        JOIN sources s ON s.id = v.source_id
        JOIN projects p ON p.id = s.project_id
        WHERE a.id = %s
        """,
        (atom_id,),
    )
    return cur.fetchone()


def leg_fts(
    cur,
    query: str,
    project: str | None,
    leg_k: int,
    include_superseded: bool,
    meta_sql: str = "",
    meta_params: list | None = None,
    as_of: str | None = None,
):
    tq = fts_query(query)
    if not tq:
        return []
    pf, pp = _project_filter(project)
    status = _atom_status_sql(include_superseded, as_of)
    mp = list(meta_params or [])
    sql = f"""
        SELECT a.id, ts_rank(a.tsv, to_tsquery('public.ru_en', %s)) AS rank
        FROM atoms a
        JOIN versions v ON a.version_id = v.id
        JOIN sources s ON a.document_id = s.id
        WHERE a.tsv @@ to_tsquery('public.ru_en', %s){status}{pf}{meta_sql}
        ORDER BY rank DESC LIMIT %s
    """
    params = [tq, tq] + pp + mp + [leg_k]
    cur.execute(sql, params)
    return [(r[0], float(r[1])) for r in cur.fetchall()]


def leg_ilike(
    cur,
    query: str,
    project: str | None,
    leg_k: int,
    include_superseded: bool,
    meta_sql: str = "",
    meta_params: list | None = None,
    as_of: str | None = None,
):
    terms = ili_terms(query)
    if not terms:
        return []
    pf, pp = _project_filter(project)
    status = _atom_status_sql(include_superseded, as_of)
    mp = list(meta_params or [])
    conds = " OR ".join(["a.content ILIKE %s" for _ in terms])
    sql = f"""
        SELECT a.id FROM atoms a
        JOIN versions v ON a.version_id = v.id
        JOIN sources s ON a.document_id = s.id
        WHERE ({conds}){status}{pf}{meta_sql}
        ORDER BY a.id LIMIT %s
    """
    params = [f"%{t}%" for t in terms] + pp + mp + [leg_k]
    cur.execute(sql, params)
    return [r[0] for r in cur.fetchall()]


def _pgvector_version(cur) -> tuple[str, float]:
    cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
    row = cur.fetchone()
    if not row:
        return "", 0.0
    v = row[0]
    try:
        parts = v.split(".")
        return v, float(parts[0]) + float(parts[1]) / 10
    except Exception:
        return v, 0.0


def _hnsw_index_name(model: str, dims: int) -> str:
    from vector_index import hnsw_index_name

    return hnsw_index_name(model, dims)


def leg_vector(
    cur,
    conn,
    qvec: list[float],
    provider: EmbeddingProvider,
    project: str | None,
    leg_k: int,
    include_superseded: bool,
    warnings: list[str],
    meta_sql: str = "",
    meta_params: list | None = None,
    as_of: str | None = None,
):
    model, dims = provider.space, provider.dims
    idx = _hnsw_index_name(model, dims)
    cur.execute(
        "SELECT 1 FROM pg_indexes WHERE indexname = %s",
        (idx,),
    )
    has_idx = cur.fetchone() is not None

    pf, pp = _project_filter(project)
    status = _atom_status_sql(include_superseded, as_of)
    mp = list(meta_params or [])
    vec_lit = "[" + ",".join(str(float(x)) for x in qvec) + "]"

    count_sql = f"""
        SELECT count(*) FROM embeddings e
        JOIN atoms a ON a.id = e.atom_id
        JOIN versions v ON v.id = a.version_id
        JOIN sources s ON s.id = v.source_id
        WHERE e.model = %s AND e.dims = %s{status}{pf}{meta_sql}
    """
    cur.execute(count_sql, [model, dims] + pp + mp)
    n_vecs = cur.fetchone()[0]

    if n_vecs == 0:
        warnings.append(f"в базе нет векторов для {model}/{dims}; выполните scripts/embed_atoms.py")
        return []

    use_exact = False
    if not has_idx:
        if n_vecs <= SEARCH_EXACT_MAX:
            warnings.append(f"нет HNSW-индекса для {model}; точное сканирование")
            use_exact = True
        else:
            warnings.append(f"нет HNSW-индекса для {model}; векторная ветка выключена")
            return []

    _, pgv_num = _pgvector_version(cur)
    dist_expr = f"(e.vector::public.vector({dims}) <=> '{vec_lit}'::public.vector({dims}))"
    sql = f"""
        SELECT a.id, {dist_expr} AS dist
        FROM embeddings e
        JOIN atoms a ON a.id = e.atom_id
        JOIN versions v ON v.id = a.version_id
        JOIN sources s ON s.id = v.source_id
        WHERE e.model = %s AND e.dims = %s{status}{pf}{meta_sql}
        ORDER BY {dist_expr}
        LIMIT %s
    """
    params = [model, dims] + pp + mp + [leg_k]

    if use_exact:
        cur.execute("SET LOCAL enable_indexscan = off")
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.execute("RESET enable_indexscan")
        return [(r[0], 1.0 - float(r[1])) for r in rows]

    cur.execute("BEGIN")
    try:
        cur.execute("SET LOCAL hnsw.ef_search = %s", (max(EMBED_EF_SEARCH, leg_k),))
        if pgv_num >= 0.8:
            cur.execute("SET LOCAL hnsw.iterative_scan = strict_order")
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if len(rows) < min(leg_k, n_vecs) and n_vecs <= SEARCH_EXACT_MAX and pgv_num < 0.8:
        warnings.append("векторная ветка неполна: обновите pgvector до ≥0.8")
        cur.execute("SET LOCAL enable_indexscan = off")
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.execute("RESET enable_indexscan")

    return [(r[0], 1.0 - float(r[1])) for r in rows]


def _dedupe_content(hits: list[Hit]) -> list[Hit]:
    seen: dict[tuple, Hit] = {}
    order = []
    for h in hits:
        key = (h.source_title, h.version_no, h.content)
        if key in seen:
            seen[key].duplicates += 1
            if h.score > seen[key].score:
                seen[key] = h
        else:
            seen[key] = h
            order.append(key)
    return [seen[k] for k in order]


def search_fts_only(
    conn,
    query: str,
    *,
    project: str | None = None,
    limit: int = 10,
    law: str | None = None,
    doc_kind: str | None = None,
    as_of: str | None = None,
    warnings: list[str] | None = None,
) -> SearchResult:
    """Только FTS + ILIKE; фильтры и metadata-leg как в hybrid."""
    warnings = list(warnings or [])
    as_of = _resolve_as_of(as_of, warnings)
    meta_sql, meta_params = _metadata_filters(law=law, doc_kind=doc_kind, as_of=as_of)
    sq = parse_structured_query(query)
    leg_cur = conn.cursor()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    ordered_ids: list[int] = []
    for aid in leg_metadata_ids(
        leg_cur, sq, project, limit, False, meta_sql, meta_params, as_of=as_of
    ):
        ordered_ids.append(aid)
    tq = fts_query(query)
    if tq:
        for aid, _ in leg_fts(
            leg_cur, query, project, limit, False, meta_sql, meta_params, as_of=as_of
        ):
            if aid not in ordered_ids and len(ordered_ids) < limit:
                ordered_ids.append(aid)
    if len(ordered_ids) < limit:
        seen = set(ordered_ids)
        for aid in leg_ilike(
            leg_cur, query, project, limit, False, meta_sql, meta_params, as_of=as_of
        ):
            if aid not in seen and len(ordered_ids) < limit:
                ordered_ids.append(aid)
                seen.add(aid)
    hits = []
    for aid in ordered_ids[:limit]:
        row = _fetch_base_row(cur, aid)
        if not row:
            continue
        meta = row["metadata"] or {}
        exact = _exact_match(row["content"], meta, sq)
        hits.append(
            Hit(
                atom_id=aid,
                content=row["content"],
                atom_type=row["atom_type"],
                metadata=meta,
                source_title=row["source_title"],
                project=row["project"],
                version_no=row["version_no"],
                matched_by=["fts"] if tq else ["ilike"],
                ranks={},
                score=0.0,
                exact=exact,
            )
        )
    if sq.article or sq.point or sq.section or sq.annex:
        exact_tier = [h for h in hits if h.exact]
        other = [h for h in hits if not h.exact]
        hits = exact_tier + other
    if hits:
        lcur = conn.cursor()
        lm = linked_by_atom(lcur, [h.atom_id for h in hits])
        for h in hits:
            h.links = [
                {
                    "type": t,
                    "content": (c or "")[:300],
                    "table_no": (m or {}).get("table_no"),
                    "fig_no": (m or {}).get("fig_no"),
                }
                for t, c, m in lm.get(h.atom_id, [])
            ]
        lcur.close()
    leg_cur.close()
    cur.close()
    if not hits and as_of:
        warnings.append(
            "нет редакции документов на указанную дату (--as-of); "
            "попробуйте другую дату или уберите фильтр"
        )
    return SearchResult(results=hits[:limit], warnings=warnings, mode_used="fts", legs={})


def search(
    conn,
    query: str,
    *,
    project: str | None = None,
    limit: int = 10,
    mode: str = "hybrid",
    atom_types: list[str] | None = None,
    include_superseded: bool = False,
    provider: EmbeddingProvider | None = None,
    provider_warnings: list[str] | None = None,
    law: str | None = None,
    doc_kind: str | None = None,
    as_of: str | None = None,
) -> SearchResult:
    warnings: list[str] = list(provider_warnings or [])
    mode = (mode or os.environ.get("SEARCH_MODE", "hybrid")).lower()
    if mode not in ("fts", "vector", "hybrid"):
        raise ValueError(f"неизвестный mode: {mode}")

    as_of_resolved = _resolve_as_of(as_of, warnings)
    meta_sql, meta_params = _metadata_filters(
        law=law, doc_kind=doc_kind, as_of=as_of_resolved
    )
    sq = parse_structured_query(query)

    if mode == "fts":
        return search_fts_only(
            conn,
            query,
            project=project,
            limit=limit,
            law=law,
            doc_kind=doc_kind,
            as_of=as_of_resolved,
            warnings=warnings,
        )

    if provider is None and mode in ("hybrid", "vector"):
        provider, pw = resolve_provider()
        warnings.extend(pw)
        log_provider_once(provider, [])

    leg_cur = conn.cursor()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    legs: dict[str, int] = {}
    rank_maps: dict[str, dict[int, int]] = {
        "fts": {},
        "ilike": {},
        "vector": {},
        "meta": {},
    }
    sim_map: dict[int, float] = {}

    leg_k = max(SEARCH_LEG_K, limit)

    meta_ids = leg_metadata_ids(
        leg_cur,
        sq,
        project or None,
        leg_k,
        include_superseded,
        meta_sql,
        meta_params,
        as_of=as_of_resolved,
    )
    for i, aid in enumerate(meta_ids, 1):
        rank_maps.setdefault("meta", {})[aid] = i

    if mode in ("fts", "hybrid"):
        fts_rows = leg_fts(
            leg_cur,
            query,
            project or None,
            leg_k,
            include_superseded,
            meta_sql,
            meta_params,
            as_of=as_of_resolved,
        )
        legs["fts"] = len(fts_rows)
        for i, (aid, _) in enumerate(fts_rows, 1):
            rank_maps["fts"][aid] = i

    need_ilike = mode in ("fts", "hybrid") and len(rank_maps["fts"]) < limit
    if need_ilike:
        ilike_ids = leg_ilike(
            leg_cur,
            query,
            project or None,
            leg_k,
            include_superseded,
            meta_sql,
            meta_params,
            as_of=as_of_resolved,
        )
        legs["ilike"] = len(ilike_ids)
        r0 = 1
        for aid in ilike_ids:
            if aid not in rank_maps["fts"]:
                rank_maps["ilike"][aid] = r0
                r0 += 1

    vector_ok = provider is not None and mode in ("hybrid", "vector")
    if vector_ok:
        # политика проектов для запроса
        leg_cur.execute("SELECT name, embed_policy FROM projects")
        restricted = []
        for name, pol in leg_cur.fetchall():
            from embed_build import effective_embed_policy, should_skip_embed_for_policy

            pk = provider.describe().get("kind", "")
            ep = effective_embed_policy(name, pol or "inherit")
            if should_skip_embed_for_policy(ep, pk):
                restricted.append(name)
        if project:
            from embed_build import effective_embed_policy, should_skip_embed_for_policy

            leg_cur.execute(
                "SELECT embed_policy FROM projects WHERE name = %s", (project,)
            )
            row = leg_cur.fetchone()
            pol = row[0] if row else "inherit"
            if should_skip_embed_for_policy(
                effective_embed_policy(project, pol),
                provider.describe().get("kind", ""),
            ):
                vector_ok = False
                warnings.append(f"векторный поиск для проекта {project} запрещён политикой")
        elif restricted:
            warnings.append(
                "векторный поиск не охватывает проекты: " + ", ".join(sorted(restricted))
            )

    if vector_ok:
        try:
            qvec = provider.embed_query(query)
            vrows = leg_vector(
                leg_cur,
                conn,
                qvec,
                provider,
                project or None,
                leg_k,
                include_superseded,
                warnings,
                meta_sql,
                meta_params,
                as_of=as_of_resolved,
            )
            legs["vector"] = len(vrows)
            min_sim = min_similarity_for_space(provider.space)
            r0 = 1
            for aid, sim in vrows:
                if sim >= min_sim:
                    rank_maps["vector"][aid] = r0
                    sim_map[aid] = sim
                    r0 += 1
        except Exception as e:
            if mode == "vector":
                warnings.append(f"режим vector недоступен: {type(e).__name__}: {e}")
            else:
                warnings.append(
                    f"векторная ветка недоступна: {type(e).__name__}; результаты только полнотекстовые"
                )
            vector_ok = False

    if mode == "vector" and not vector_ok:
        leg_cur.close()
        cur.close()
        return SearchResult(results=[], warnings=warnings, mode_used="vector", legs=legs)

    all_ids = (
        set(rank_maps["fts"])
        | set(rank_maps["ilike"])
        | set(rank_maps["vector"])
        | set(rank_maps.get("meta", {}))
    )
    weights = {
        "fts": SEARCH_W_FTS,
        "ilike": SEARCH_W_ILIKE,
        "vector": SEARCH_W_VEC,
        "meta": SEARCH_W_FTS,
    }
    scored: list[tuple[float, int, Hit]] = []

    for aid in all_ids:
        ranks = {}
        matched = []
        for leg in ("meta", "fts", "ilike", "vector"):
            if aid in rank_maps.get(leg, {}):
                ranks[leg] = rank_maps[leg][aid]
                matched.append(leg)
        if not ranks:
            continue
        score = rrf_score(ranks, weights)
        row = _fetch_base_row(cur, aid)
        if not row:
            continue
        if atom_types and row["atom_type"] not in atom_types:
            continue
        meta = row["metadata"] or {}
        exact = _exact_match(row["content"], meta, sq)
        note = None
        if matched == ["vector"]:
            note = "семантическое совпадение — проверьте формулировку по цитате"
        h = Hit(
            atom_id=aid,
            content=row["content"],
            atom_type=row["atom_type"],
            metadata=meta,
            source_title=row["source_title"],
            project=row["project"],
            version_no=row["version_no"],
            matched_by=matched,
            ranks=ranks,
            score=score,
            similarity=sim_map.get(aid),
            exact=exact,
            match_note=note,
        )
        fts_rank = ranks.get("fts", 10**9)
        scored.append((score, fts_rank, h))

    scored.sort(key=lambda x: (-x[0], x[1], x[2].atom_id))
    hits = [h for _, _, h in scored]

    if sq.article or sq.point or sq.section or sq.annex:
        exact_tier = [h for h in hits if h.exact]
        other = [h for h in hits if not h.exact]
        exact_tier.sort(key=lambda h: (-h.score, h.ranks.get("fts", 10**9), h.atom_id))
        other.sort(key=lambda h: (-h.ranks.get("meta", 10**9), -h.score, h.atom_id))
        hits = exact_tier + other

    hits = _dedupe_content(hits)[:limit]

    if not hits:
        if warnings or mode != "fts":
            pass
        # «не найдено» — пустой список; вызывающий форматирует текст

    # links одним запросом
    if hits:
        lcur = conn.cursor()
        lm = linked_by_atom(lcur, [h.atom_id for h in hits])
        for h in hits:
            h.links = [
                {
                    "type": t,
                    "content": (c or "")[:300],
                    "table_no": (m or {}).get("table_no"),
                    "fig_no": (m or {}).get("fig_no"),
                }
                for t, c, m in lm.get(h.atom_id, [])
            ]
        lcur.close()

    leg_cur.close()
    cur.close()
    if not hits and as_of_resolved:
        warnings = [
            w
            for w in warnings
            if "в базе нет векторов" not in w and "векторная ветка недоступна" not in w
        ]
        if not any("нет редакции" in w for w in warnings):
            warnings.append(
                "нет редакции документов на указанную дату (--as-of); "
                "попробуйте другую дату или уберите фильтр"
            )
    mode_used = mode
    if mode == "hybrid" and not vector_ok and provider is None:
        mode_used = "fts"
    return SearchResult(results=hits, warnings=warnings, mode_used=mode_used, legs=legs)


def hit_to_dict(h: Hit) -> dict[str, Any]:
    meta = h.metadata or {}
    return {
        "atom_id": h.atom_id,
        "id": h.atom_id,
        "content": h.content[:500],
        "atom_type": h.atom_type,
        "page": meta.get("page") or "?",
        "source": h.source_title,
        "source_title": h.source_title,
        "project": h.project,
        "version": h.version_no,
        "version_no": h.version_no,
        "section": meta.get("section_path"),
        "law": meta.get("law"),
        "article": meta.get("article"),
        "point": meta.get("point"),
        "redaction": meta.get("redaction"),
        "effective_date": meta.get("effective_date"),
        "tags": meta.get("tags", []),
        "summary": meta.get("summary", ""),
        "matched_by": h.matched_by,
        "ranks": h.ranks,
        "score": h.score,
        "similarity": h.similarity,
        "exact": h.exact,
        "match_note": h.match_note,
        "citation": format_citation(meta, h.source_title),
        "linked": h.links,
    }
