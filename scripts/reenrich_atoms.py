#!/usr/bin/env python3
"""Дообогащение текст-атомов без тегов после сбоев LLM в import_document.py.

  export $(grep PG_DSN ~/.hermes/.env | head -1)
  python3 scripts/reenrich_atoms.py --source <source_id>

Использует ту же enrich_batch (DeepSeek v4-flash, батчи по 5, контекст-приписка),
потом подсказывает запустить normalize_links.py --version <N>.
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from import_document import enrich_batch, get_pg  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Дообогащение атомов без тегов")
    ap.add_argument("--source", type=int, required=True, help="id источника в БД")
    ap.add_argument("--batch", type=int, default=5)
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    conn = get_pg()
    cur = conn.cursor()

    cur.execute("SELECT id, version_no FROM versions WHERE source_id = %s ORDER BY version_no DESC LIMIT 1", (args.source,))
    version_id, vno = cur.fetchone()
    cur.execute("SELECT title FROM sources WHERE id = %s", (args.source,))
    doc_title = cur.fetchone()[0]

    cur.execute(
        """
        SELECT a.id, a.ordinal, a.content
        FROM atoms a JOIN versions v ON a.version_id = v.id
        WHERE a.version_id = %s AND a.atom_type = 'text'
          AND NOT (jsonb_typeof(a.metadata -> 'tags') = 'array'
                   AND jsonb_array_length(a.metadata -> 'tags') > 0)
        ORDER BY a.ordinal
        """,
        (version_id,),
    )
    rows = cur.fetchall()
    print(f"Источник #{args.source} v{vno}: не размеченных текст-атомов: {len(rows)}")
    if not rows:
        return

    atoms = [{"id": rid, "ordinal": ord_, "atom_type": "text", "content": c} for rid, ord_, c in rows]
    batches = [atoms[i:i + args.batch] for i in range(0, len(atoms), args.batch)]

    results = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {}
        prev_tail = ""
        for bi, batch in enumerate(batches):
            prev_content = batches[bi - 1][-1]["content"] if bi > 0 else ""
            prev_tail = (prev_content or "")[-150:]
            futures[ex.submit(enrich_batch, batch, doc_title, prev_tail)] = bi
        for fut in as_completed(futures):
            bi = futures[fut]
            try:
                results[bi] = fut.result()
            except Exception as e:
                print(f"      ⚠ сбой батча {bi}: {e}")
                results[bi] = None

    updated = 0
    for bi in sorted(results):
        batch_res = results[bi]
        if not batch_res:
            continue
        for atom in batch_res:
            meta = atom.get("metadata", {})
            if not meta.get("tags"):
                continue
            cur.execute(
                "UPDATE atoms SET metadata = metadata || %s::jsonb WHERE id = %s",
                (json.dumps(meta, ensure_ascii=False), atom["id"]),
            )
            updated += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"Обновлено атомов: {updated}")
    if updated:
        print(f"Затем: python3 scripts/normalize_links.py --version-id {version_id}")


if __name__ == "__main__":
    main()
