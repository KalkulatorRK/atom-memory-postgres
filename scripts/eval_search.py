#!/usr/bin/env python3
"""Оценка качества поиска по golden set (recall, MRR, nDCG)."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import psycopg2

from _common import get_dsn
from search_core import search


def recall_at_k(relevant: set, ranked: list, k: int) -> float:
    if not relevant:
        return 0.0
    hit = sum(1 for x in ranked[:k] if x in relevant)
    return hit / len(relevant)


def mrr_at_k(relevant: set, ranked: list, k: int) -> float:
    for i, x in enumerate(ranked[:k], 1):
        if x in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(relevant: set, ranked: list, k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 2) for i, x in enumerate(ranked[:k]) if x in relevant)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / ideal if ideal else 0.0


def load_golden(path: Path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def atom_key(cur, key: str) -> int | None:
    # key: source_title|page|sha1prefix
    parts = key.split("|")
    if len(parts) < 3:
        return None
    title, page, pref = parts[0], parts[1], parts[2]
    cur.execute(
        """
        SELECT a.id FROM atoms a
        JOIN sources s ON s.id = a.document_id
        WHERE s.title = %s AND (a.metadata->>'page') = %s
          AND a.status = 'active'
        """,
        (title, page),
    )
    for (aid,) in cur.fetchall():
        cur.execute("SELECT content FROM atoms WHERE id=%s", (aid,))
        content = cur.fetchone()[0]
        import hashlib

        h = hashlib.sha1(content.encode()).hexdigest()[:12]
        if h == pref:
            return aid
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", required=True)
    ap.add_argument("--modes", default="fts,hybrid")
    ap.add_argument("--k", default="5,10")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    golden = load_golden(Path(args.golden))
    modes = [m.strip() for m in args.modes.split(",")]
    ks = [int(x) for x in args.k.split(",")]

    conn = psycopg2.connect(get_dsn())
    cur = conn.cursor()
    report = {"modes": {}, "gates": {}}

    for mode in modes:
        stats = {f"recall@{k}": [] for k in ks}
        stats.update({f"mrr@{max(ks)}": [], f"ndcg@{max(ks)}": []})
        not_found = 0
        for row in golden:
            sr = search(conn, row["query"], project=row.get("project") or None, limit=max(ks), mode=mode)
            rel = set()
            for k in row.get("relevant", []):
                aid = atom_key(cur, k)
                if aid:
                    rel.add(aid)
            ranked = [h.atom_id for h in sr.results]
            if not ranked and row.get("kind") == "negative":
                not_found += 1
            for k in ks:
                stats[f"recall@{k}"].append(recall_at_k(rel, ranked, k))
            stats[f"mrr@{max(ks)}"].append(mrr_at_k(rel, ranked, max(ks)))
            stats[f"ndcg@{max(ks)}"].append(ndcg_at_k(rel, ranked, max(ks)))
        report["modes"][mode] = {
            k: (sum(v) / len(v) if v else 0.0) for k, v in stats.items()
        }
        if any(r.get("kind") == "negative" for r in golden):
            neg = [r for r in golden if r.get("kind") == "negative"]
            report["modes"][mode]["negative_not_found_rate"] = not_found / len(neg)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
