"""Фикстуры: fake-эмбеддер, блок сети, заглушка LLM."""
import os
import socket
from unittest.mock import patch

import pytest

_orig_create_connection = socket.create_connection
_orig_urllib3_create_connection = None
try:
    import urllib3.util.connection as _uc

    _orig_urllib3_create_connection = _uc.create_connection
except Exception:
    pass


def _guard_create_connection(address, *args, **kwargs):
    host = address[0] if isinstance(address, tuple) else str(address)
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(f"сетевое соединение запрещено в тестах: {host}")
    if "socket_options" in kwargs and _orig_urllib3_create_connection is not None:
        return _orig_urllib3_create_connection(address, *args, **kwargs)
    return _orig_create_connection(address, *args, **kwargs)


@pytest.fixture(autouse=True)
def _embed_fake_and_network_guard(monkeypatch):
    monkeypatch.setenv("EMBED_PROVIDER", "fake")
    monkeypatch.delenv("EMBED_API_KEY", raising=False)
    monkeypatch.delenv("EMBED_LOCAL_MODEL", raising=False)
    monkeypatch.setitem(os.environ, "PYTEST_CURRENT_TEST", "1")
    monkeypatch.setattr(socket, "create_connection", _guard_create_connection)
    if _orig_urllib3_create_connection is not None:
        import urllib3.util.connection as uc

        monkeypatch.setattr(uc, "create_connection", _guard_create_connection)
    yield


@pytest.fixture(autouse=True)
def _fake_llm():
    def fake_enrich(batch, doc_title="ГОСТ", prev_tail=""):
        out = []
        for a in batch:
            meta = dict(a.get("metadata") or {})
            meta.setdefault("tags", ["test"])
            a = dict(a)
            a["metadata"] = meta
            out.append(a)
        return out, prev_tail

    with patch("import_document.enrich_batch", fake_enrich):
        yield
