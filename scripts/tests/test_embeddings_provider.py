import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from embeddings import (
    CloudEmbeddingProvider,
    EmbedDimsMismatch,
    FakeEmbeddingProvider,
    resolve_provider,
)


def test_provider_none_without_env(monkeypatch, capsys):
    monkeypatch.delenv("EMBED_API_KEY", raising=False)
    monkeypatch.setenv("EMBED_PROVIDER", "auto")
    p, w = resolve_provider({k: os.environ.get(k, "") for k in os.environ})
    monkeypatch.delenv("EMBED_API_KEY", raising=False)
    env = {k: v for k, v in os.environ.items() if k != "EMBED_API_KEY"}
    env["EMBED_PROVIDER"] = "auto"
    env.pop("EMBED_API_KEY", None)
    p, w = resolve_provider(env)
    assert p is None
    assert len(w) == 1
    assert "EMBED_API_KEY" in w[0]


def test_provider_fake():
    p, w = resolve_provider({"EMBED_PROVIDER": "fake"})
    assert isinstance(p, FakeEmbeddingProvider)


class _Handler(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self):
        _Handler.calls += 1
        ln = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(ln))
        assert body.get("dimensions") == 768
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        emb = [0.1] * 768
        self.wfile.write(
            json.dumps({"data": [{"index": 0, "embedding": emb}], "usage": {"total_tokens": 3}}).encode()
        )

    def log_message(self, *args):
        return


def test_provider_cloud_when_key(monkeypatch):
    monkeypatch.setenv("EMBED_API_KEY", "sk-test-key-not-real")
    monkeypatch.setenv("EMBED_BASE_URL", "http://127.0.0.1:8765/v1")
    srv = HTTPServer(("127.0.0.1", 8765), _Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    time.sleep(0.05)
    p, _ = resolve_provider(os.environ)
    assert p is not None
    v = p.embed_query("hello")
    assert len(v) == 768
    srv.shutdown()


def test_fake_deterministic():
    p = FakeEmbeddingProvider()
    a = p.embed_query("тест")
    b = p.embed_query("тест")
    assert a == b
    s = sum(x * x for x in a)
    assert abs(s - 1.0) < 1e-5


def test_cloud_dims_mismatch(monkeypatch):
    monkeypatch.setenv("EMBED_API_KEY", "k")
    monkeypatch.setenv("EMBED_BASE_URL", "http://127.0.0.1:8766/v1")

    class BadHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                json.dumps({"data": [{"index": 0, "embedding": [0.0] * 1536}]}).encode()
            )

        def log_message(self, *args):
            return

    srv = HTTPServer(("127.0.0.1", 8766), BadHandler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    time.sleep(0.05)
    p = CloudEmbeddingProvider(api_key="k", base_url="http://127.0.0.1:8766/v1", model="m", dims=768)
    with pytest.raises(EmbedDimsMismatch):
        p.embed_query("x")
    srv.shutdown()


def test_api_key_never_logged(monkeypatch, capsys):
    secret = "sk-super-secret-key-12345"
    monkeypatch.setenv("EMBED_API_KEY", secret)
    monkeypatch.setenv("EMBED_BASE_URL", "http://127.0.0.1:8767/v1")

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(401)
            self.end_headers()

        def log_message(self, *args):
            return

    srv = HTTPServer(("127.0.0.1", 8767), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    time.sleep(0.05)
    p = CloudEmbeddingProvider(api_key=secret, base_url="http://127.0.0.1:8767/v1", model="m", dims=768)
    try:
        p.embed_query("q")
    except RuntimeError as e:
        assert secret not in str(e)
    captured = capsys.readouterr()
    assert secret not in captured.err + captured.out
    srv.shutdown()
