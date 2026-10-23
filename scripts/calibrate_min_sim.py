#!/usr/bin/env python3
"""Оценка порога EMBED_MIN_SIM на fake-эмбеддере (без сети).

Запуск: EMBED_PROVIDER=fake python3 calibrate_min_sim.py

Печатает распределение cosine similarity для пар «запрос ↔ релевантный/нерелевантный»
и предлагает консервативный порог. Для production подстройте по eval_search.py на своих данных.
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from embeddings import FakeEmbeddingProvider  # noqa: E402


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def main() -> int:
    os.environ.setdefault("EMBED_PROVIDER", "fake")
    p = FakeEmbeddingProvider()
    pairs_pos = [
        ("ГОСТ 7512-82 ультразвуковой контроль", "ГОСТ 7512-82 методы ультразвукового контроля"),
        ("ст. 475 УК РФ", "статья 475 ответственность за нарушение"),
        ("сварной шов дефекты", "дефекты сварного шва контроль качества"),
    ]
    pairs_neg = [
        ("ГОСТ 7512-82", "погода завтра солнечно"),
        ("ст. 475", "рецепт борща с говядиной"),
        ("сварной шов", "курс доллара центробанк"),
    ]
    pos_sims = []
    neg_sims = []
    for q, doc in pairs_pos:
        pos_sims.append(_cos(p.embed_query(q), p.embed_query(doc)))
    for q, doc in pairs_neg:
        neg_sims.append(_cos(p.embed_query(q), p.embed_query(doc)))

    pos_min = min(pos_sims)
    neg_max = max(neg_sims)
    suggested = max(0.35, min(0.72, (pos_min + neg_max) / 2))
    print("fake:hash-v1 — калибровка EMBED_MIN_SIM (ориентир, не замена eval на ваших данных)")
    print(f"  релевантные пары: min={pos_min:.3f}  sims={[round(x,3) for x in pos_sims]}")
    print(f"  нерелевантные:    max={neg_max:.3f}  sims={[round(x,3) for x in neg_sims]}")
    print(f"  предложенный порог для fake: {suggested:.3f}")
    print("  облако (text-embedding-3-small): дефолт 0.72 консервативен; задайте EMBED_MIN_SIM")
    print("  или JSON {\"cloud:text-embedding-3-small\": 0.65} после scripts/eval_search.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
