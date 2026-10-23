#!/usr/bin/env python3
"""Smoke-бенчмарк SQL-веток поиска на синтетических данных."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import psycopg2

from embeddings import FakeEmbeddingProvider
from search_core import leg_fts, leg_vector


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--atoms", type=int, default=2000)
    ap.add_argument("--report", default="-")
    args = ap.parse_args()

    dsn = os.environ.get("TEST_PG_DSN") or os.environ.get("PG_DSN")
    if not dsn:
        print("нужен TEST_PG_DSN", file=sys.stderr)
        return 1

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    provider = FakeEmbeddingProvider()
    qvec = provider.embed_query("тестовый запрос")
    warnings = []

    t0 = time.perf_counter()
    leg_fts(cur, "контроль качества", None, 10, False)
    fts_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    try:
        leg_vector(cur, conn, qvec, provider, None, 10, False, warnings)
    except Exception as e:
        warnings.append(str(e))
    vec_ms = (time.perf_counter() - t0) * 1000

    report = {
        "atoms_requested": args.atoms,
        "fts_p50_ms": round(fts_ms, 2),
        "vector_p50_ms": round(vec_ms, 2),
        "warnings": warnings,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report == "-":
        print(text)
    else:
        open(args.report, "w", encoding="utf-8").write(text)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
