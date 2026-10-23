"""Имена HNSW-индексов для пространств эмбеддингов (единый алгоритм для SQL, поиска, admin.sh)."""
from __future__ import annotations

import re

# Канонические slug — совпадают с references/migrations/0004_vector_search.sql
_HNSW_SLUG_CANONICAL: dict[str, str] = {
    "cloud:text-embedding-3-small": "cloud_te3s",
    "fake:hash-v1": "fake_hash_v1",
}


def hnsw_model_slug(model: str) -> str:
    if model in _HNSW_SLUG_CANONICAL:
        return _HNSW_SLUG_CANONICAL[model]
    return re.sub(r"[^a-z0-9]+", "_", model.lower()).strip("_")


def hnsw_index_name(model: str, dims: int) -> str:
    return f"idx_emb_hnsw_{hnsw_model_slug(model)}_{dims}"
