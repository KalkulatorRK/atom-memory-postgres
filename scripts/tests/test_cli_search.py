import os


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_cli_default_hybrid_warns_without_provider(monkeypatch, capsys):
    monkeypatch.delenv("EMBED_API_KEY", raising=False)
    monkeypatch.setenv("EMBED_PROVIDER", "auto")
    env = os.environ.copy()
    env.pop("EMBED_API_KEY", None)
    # без PG — только проверим, что модуль импортируется
    from embeddings import resolve_provider

    p, w = resolve_provider(env)
    assert p is None
    assert len(w) == 1


def test_mcp_mode_enum_in_fallback():
    import memory_mcp_server as m

    assert "memory_search" in open(m.__file__, encoding="utf-8").read()
    src = open(m.__file__, encoding="utf-8").read()
    assert '"enum": ["fts", "vector", "hybrid"]' in src


def test_eval_metrics():
    from eval_search import mrr_at_k, ndcg_at_k, recall_at_k

    rel = {1, 2}
    ranked = [2, 3, 1]
    assert recall_at_k(rel, ranked, 5) == 1.0
    assert mrr_at_k(rel, ranked, 5) == 1.0
    assert ndcg_at_k(rel, ranked, 5) > 0
