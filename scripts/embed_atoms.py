#!/usr/bin/env python3
"""Backfill эмбеддингов для активных атомов."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import psycopg2
from psycopg2.extras import Json

from _common import get_dsn
from embed_build import (
    build_embed_text,
    compute_content_hash,
    effective_embed_policy,
    should_skip_embed_for_policy,
)
from embeddings import (
    estimate_tokens,
    log_provider_once,
    resolve_provider,
    truncate_to_tokens,
)


def _select_atoms(cur, project: str | None, version_id: int | None):
    sql = """
        SELECT a.id, a.atom_type, a.content, a.metadata, s.title AS source_title,
               p.name AS project_name, p.embed_policy
        FROM atoms a
        JOIN versions v ON v.id = a.version_id
        JOIN sources s ON s.id = v.source_id
        JOIN projects p ON p.id = s.project_id
        WHERE a.status = 'active'
    """
    params: list = []
    if project:
        sql += " AND p.name = %s"
        params.append(project)
    if version_id:
        sql += " AND v.id = %s"
        params.append(version_id)
    sql += " ORDER BY a.id"
    cur.execute(sql, params)
    return cur.fetchall()


def embed_atoms_for_version(
    version_id: int,
    *,
    conn=None,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[int, list[str]]:
    close = False
    if conn is None:
        conn = psycopg2.connect(get_dsn())
        close = True
    warnings: list[str] = []
    provider, pw = resolve_provider()
    warnings.extend(pw)
    log_provider_once(provider, [])
    if provider is None:
        warnings.append("нечем считать эмбеддинги")
        if close:
            conn.close()
        return 0, warnings

    kind = provider.describe().get("kind", "")
    space, dims = provider.space, provider.dims
    cur = conn.cursor()
    rows = _select_atoms(cur, None, version_id)
    todo = []
    skipped = {"policy": 0, "image": 0, "empty": 0}
    for aid, atype, content, meta, stitle, pname, pol in rows:
        ep = effective_embed_policy(pname, pol or "inherit")
        if should_skip_embed_for_policy(ep, kind):
            skipped["policy"] += 1
            continue
        atom = {"atom_type": atype, "content": content, "metadata": meta or {}}
        etext, skip = build_embed_text(atom, stitle or "")
        if skip:
            skipped[skip.split(":")[0] if ":" in skip else skip] = skipped.get(
                skip, 0
            ) + 1
            continue
        etext, _trunc = truncate_to_tokens(etext, provider.max_input_tokens)
        ch = compute_content_hash(space, dims, etext)
        if not force:
            cur.execute(
                "SELECT content_hash FROM embeddings WHERE atom_id=%s AND model=%s AND dims=%s",
                (aid, space, dims),
            )
            ex = cur.fetchone()
            if ex and ex[0] == ch:
                continue
        todo.append((aid, etext, ch, _trunc))

    if dry_run:
        tok = sum(estimate_tokens(t[1]) for t in todo)
        print(
            f"dry-run: {len(todo)} атомов, ~{tok} токенов, space={space}, dims={dims}",
            file=sys.stderr,
        )
        cur.close()
        if close:
            conn.close()
        return 0, warnings

    if not todo:
        cur.close()
        if close:
            conn.close()
        return 0, warnings

    texts = [t[1] for t in todo]
    vecs = provider.embed_passages(texts)
    for (aid, etext, ch, trunc), vec in zip(todo, vecs):
        meta = {"truncated": trunc}
        cur.execute(
            """
            INSERT INTO embeddings (atom_id, model, dims, vector, content_hash, embed_meta, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, now())
            ON CONFLICT (atom_id, model, dims) DO UPDATE SET
              vector = EXCLUDED.vector,
              content_hash = EXCLUDED.content_hash,
              embed_meta = EXCLUDED.embed_meta,
              updated_at = now()
            """,
            (aid, space, dims, vec, ch, Json(meta)),
        )
    conn.commit()
    cur.execute(
        "INSERT INTO journal (op_type, details) VALUES ('embed', %s::jsonb)",
        (
            json.dumps(
                {
                    "space": space,
                    "dims": dims,
                    "embedded": len(todo),
                    "skipped": skipped,
                },
                ensure_ascii=False,
            ),
        ),
    )
    conn.commit()
    cur.close()
    if close:
        conn.close()
    return len(todo), warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project")
    ap.add_argument("--model")
    ap.add_argument("--dims", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--prune-superseded", action="store_true")
    ap.add_argument("--prune-space")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--set-policy", nargs=2, metavar=("PROJECT", "POLICY"))
    args = ap.parse_args()

    if args.set_policy:
        conn = psycopg2.connect(get_dsn())
        cur = conn.cursor()
        cur.execute(
            "UPDATE projects SET embed_policy=%s WHERE name=%s",
            (args.set_policy[1], args.set_policy[0]),
        )
        if cur.rowcount == 0:
            conn.rollback()
            conn.close()
            print(
                f"Ошибка: проект {args.set_policy[0]!r} не найден",
                file=sys.stderr,
            )
            return 1
        conn.commit()
        conn.close()
        print(f"embed_policy={args.set_policy[1]} для {args.set_policy[0]}")
        return 0

    if args.model:
        os.environ["EMBED_MODEL"] = args.model
    if args.dims:
        os.environ["EMBED_DIMS"] = str(args.dims)

    provider, warnings = resolve_provider()
    for w in warnings:
        print(w, file=sys.stderr)
    if provider is None:
        print("нечем считать эмбеддинги", file=sys.stderr)
        return 2

    conn = psycopg2.connect(get_dsn())
    cur = conn.cursor()

    if args.prune_superseded:
        if not args.yes:
            print("нужен --yes для --prune-superseded", file=sys.stderr)
            return 1
        cur.execute(
            """
            DELETE FROM embeddings e USING atoms a
            WHERE e.atom_id = a.id AND a.status = 'superseded'
            """
        )
        conn.commit()

    if args.prune_space:
        if not args.yes:
            print("нужен --yes для --prune-space", file=sys.stderr)
            return 1
        model, dims_s = args.prune_space.split(":", 1)
        if ":" in dims_s:
            m, d = args.prune_space.rsplit(":", 1)
            model, dims_s = m, d
        cur.execute(
            "DELETE FROM embeddings WHERE model=%s AND dims=%s",
            (model if ":" in args.prune_space else provider.space, int(dims_s)),
        )
        conn.commit()

    kind = provider.describe().get("kind", "")
    space, dims = provider.space, provider.dims
    rows = _select_atoms(cur, args.project, None)
    if args.limit:
        rows = rows[: args.limit]

    todo = []
    skipped = {"policy": 0, "image_no_caption": 0, "empty": 0}
    budget = os.environ.get("EMBED_MAX_TOKENS_PER_RUN")
    budget_left = int(budget) if budget else None
    tokens_used = 0
    price = os.environ.get("EMBED_PRICE_PER_1M_TOKENS")

    for aid, atype, content, meta, stitle, pname, pol in rows:
        ep = effective_embed_policy(pname, pol or "inherit")
        if should_skip_embed_for_policy(ep, kind):
            skipped["policy"] += 1
            continue
        atom = {"atom_type": atype, "content": content, "metadata": meta or {}}
        etext, skip = build_embed_text(atom, stitle or "")
        if skip:
            skipped[skip] = skipped.get(skip, 0) + 1
            continue
        etext, trunc = truncate_to_tokens(etext, provider.max_input_tokens)
        ch = compute_content_hash(space, dims, etext)
        if not args.force:
            cur.execute(
                "SELECT content_hash FROM embeddings WHERE atom_id=%s AND model=%s AND dims=%s",
                (aid, space, dims),
            )
            ex = cur.fetchone()
            if ex and ex[0] == ch:
                continue
        tkn = estimate_tokens(etext)
        if budget_left is not None and tokens_used + tkn > budget_left:
            print("бюджет исчерпан, повторите запуск", file=sys.stderr)
            conn.close()
            return 3
        todo.append((aid, etext, ch, trunc))
        tokens_used += tkn

    if args.dry_run:
        cost = ""
        if price:
            cost = f", ~${tokens_used * float(price) / 1e6:.4f}"
        print(
            f"dry-run: {len(todo)} атомов, токенов ~{tokens_used}{cost}, space={space}",
            file=sys.stderr,
        )
        conn.close()
        return 0

    t0 = time.time()
    partial = False
    done = 0
    for i in range(0, len(todo), args.batch):
        batch = todo[i : i + args.batch]
        try:
            vecs = provider.embed_passages([b[1] for b in batch])
        except Exception as e:
            print(f"батч {i}: {e}", file=sys.stderr)
            partial = True
            break
        for (aid, etext, ch, trunc), vec in zip(batch, vecs):
            cur.execute(
                """
                INSERT INTO embeddings (atom_id, model, dims, vector, content_hash, embed_meta, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, now())
                ON CONFLICT (atom_id, model, dims) DO UPDATE SET
                  vector = EXCLUDED.vector,
                  content_hash = EXCLUDED.content_hash,
                  embed_meta = EXCLUDED.embed_meta,
                  updated_at = now()
                """,
                (aid, space, dims, vec, ch, Json({"truncated": trunc})),
            )
        conn.commit()
        done += len(batch)
        if done % (args.batch * 5) == 0 or done == len(todo):
            eta = ""
            print(
                f"обработано {done}/{len(todo)}, пропущено {skipped}, токенов {tokens_used}{eta}",
                file=sys.stderr,
            )

    cur.execute(
        "INSERT INTO journal (op_type, details) VALUES ('embed', %s::jsonb)",
        (
            json.dumps(
                {
                    "space": space,
                    "embedded": done,
                    "skipped": skipped,
                    "tokens": tokens_used,
                    "duration_sec": round(time.time() - t0, 2),
                },
                ensure_ascii=False,
            ),
        ),
    )
    conn.commit()
    conn.close()
    return 4 if partial else 0


if __name__ == "__main__":
    sys.exit(main())
