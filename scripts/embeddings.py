"""Провайдеры эмбеддингов: cloud (OpenAI-compatible), local, fake, none."""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Protocol

import requests

DEFAULT_CLOUD_MODEL = "text-embedding-3-small"
DEFAULT_CLOUD_SPACE = f"cloud:{DEFAULT_CLOUD_MODEL}"
FAKE_SPACE = "fake:hash-v1"


class EmbedDimsMismatch(Exception):
    """Длина вектора от провайдера не совпадает с ожидаемой."""


class EmbeddingProvider(Protocol):
    space: str
    dims: int
    max_input_tokens: int

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...

    def describe(self) -> dict:
        ...


_logged_provider: str | None = None
_cloud_warned = False


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return int(v)


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return float(v)


def load_env_secret(*keys: str) -> str:
    """Ключ из env или ~/.hermes/.env (как LLM), без логирования значения."""
    for k in keys:
        v = os.environ.get(k, "")
        if v:
            return v
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.isfile(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                for k in keys:
                    if line.startswith(f"{k}="):
                        return line.strip().split("=", 1)[1]
    return ""


def _normalize_l2(vec: list[float]) -> list[float]:
    s = math.sqrt(sum(x * x for x in vec))
    if s <= 0:
        return vec
    return [x / s for x in vec]


def estimate_tokens(text: str) -> int:
    try:
        import tiktoken  # noqa: F401

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, (len(text) + 2) // 3)


def truncate_to_tokens(text: str, max_tokens: int) -> tuple[str, bool]:
    if estimate_tokens(text) <= max_tokens:
        return text, False
    # грубо по символам, затем по границе строки
    approx = max_tokens * 3
    cut = text[:approx]
    nl = cut.rfind("\n")
    if nl > approx // 4:
        cut = cut[:nl]
    return cut, True


def content_hash(space: str, dims: int, embed_text: str) -> str:
    payload = f"{space}:{dims}\n{embed_text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cloud_canonical_model(model: str) -> str:
    return f"cloud:{model}"


def parse_retry_after(value: str | None) -> float:
    if not value:
        return 0.0
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(value)
        return max(0.0, dt.timestamp() - time.time())
    except Exception:
        return 0.0


def _host_from_base_url(base_url: str) -> str:
    p = urllib.parse.urlparse(base_url)
    return p.hostname or base_url


def is_loopback_host(host: str) -> bool:
    return host in ("localhost", "127.0.0.1", "::1")


def log_provider_once(provider: EmbeddingProvider | None, warnings: list[str]) -> None:
    global _logged_provider
    key = "none" if provider is None else provider.space
    if _logged_provider == key:
        return
    _logged_provider = key
    for w in warnings:
        print(w, file=__import__("sys").stderr)
    if provider is not None:
        d = provider.describe()
        host = d.get("host", "")
        print(
            f"эмбеддинги: kind={d.get('kind')} model={d.get('model')} dims={d.get('dims')} host={host}",
            file=__import__("sys").stderr,
        )


def warn_cloud_send_once(host: str) -> None:
    global _cloud_warned
    if _cloud_warned or is_loopback_host(host):
        return
    _cloud_warned = True
    print(
        f"Текст атомов/запросов отправляется на {host} (EMBED_BASE_URL). "
        "Отключить: EMBED_PROVIDER=none или embed_policy проекта.",
        file=__import__("sys").stderr,
    )


@dataclass
class FakeEmbeddingProvider:
    space: str = FAKE_SPACE
    dims: int = 768
    max_input_tokens: int = 8192
    _synonyms: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        self.dims = _env_int("EMBED_DIMS", self.dims)
        path = os.environ.get("EMBED_FAKE_SYNONYMS")
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                self._synonyms = json.load(f)

    def describe(self) -> dict:
        return {"kind": "fake", "model": "hash-v1", "dims": self.dims, "host": ""}

    def _tokenize(self, text: str) -> list[str]:
        toks = re.findall(r"\w+", text.lower(), re.UNICODE)
        out = []
        for t in toks:
            out.append(self._synonyms.get(t, t))
        return out

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for tok in self._tokenize(text):
            h = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "big") % self.dims
            sign = 1.0 if h[4] % 2 == 0 else -1.0
            vec[idx] += sign
        for i in range(len(text) - 2):
            tri = text[i : i + 3].lower()
            h = hashlib.blake2b(tri.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "big") % self.dims
            sign = 1.0 if h[4] % 2 == 0 else -1.0
            vec[idx] += sign * 0.5
        return _normalize_l2(vec)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


@dataclass
class CloudEmbeddingProvider:
    api_key: str
    base_url: str
    model: str
    dims: int
    send_dimensions: bool = True
    batch_size: int = 64
    max_batch_tokens: int = 100_000
    timeout: float = 30.0
    max_retries: int = 5
    query_timeout: float = 5.0
    query_max_retries: int = 2

    max_input_tokens: int = 8192

    @property
    def space(self) -> str:
        return cloud_canonical_model(self.model)

    def describe(self) -> dict:
        host = _host_from_base_url(self.base_url)
        return {
            "kind": "cloud",
            "model": self.model,
            "dims": self.dims,
            "host": host,
        }

    def _post(self, payload: dict, *, timeout: float, max_retries: int) -> dict:
        host = _host_from_base_url(self.base_url)
        if not is_loopback_host(host):
            parsed = urllib.parse.urlparse(self.base_url)
            if parsed.scheme != "https":
                raise RuntimeError("EMBED_BASE_URL должен использовать HTTPS (кроме loopback)")
        url = self.base_url.rstrip("/") + "/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        delay = 1.0
        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=timeout)
            except (requests.Timeout, requests.ConnectionError) as e:
                last_err = e
                if attempt >= max_retries:
                    raise
                time.sleep(delay + random.uniform(0, 0.25))
                delay = min(delay * 2, 60)
                continue
            if r.status_code in (429, 503, 502, 504):
                if attempt >= max_retries:
                    r.raise_for_status()
                ra = parse_retry_after(r.headers.get("Retry-After"))
                time.sleep(max(delay, ra) + random.uniform(0, 0.25))
                delay = min(delay * 2, 60)
                continue
            if r.status_code in (400, 401, 403, 404, 422):
                if r.status_code in (401, 403):
                    raise RuntimeError("проверьте EMBED_API_KEY")
                raise RuntimeError(f"embeddings API {r.status_code}: {r.text[:200]}")
            r.raise_for_status()
            return r.json()
        if last_err:
            raise last_err
        raise RuntimeError("embeddings request failed")

    def _parse_vectors(self, data: dict, n: int) -> list[list[float]]:
        items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
        if len(items) != n:
            raise RuntimeError("embeddings: число векторов не совпало с входом")
        out = []
        for item in items:
            vec = item.get("embedding")
            if not isinstance(vec, list):
                raise RuntimeError("embeddings: неверный формат embedding")
            if len(vec) != self.dims:
                raise EmbedDimsMismatch(
                    f"ожидалось {self.dims} измерений, получено {len(vec)} "
                    "(провайдер игнорирует dimensions? EMBED_SEND_DIMENSIONS=0 и EMBED_DIMS=<нативная>)"
                )
            fv = []
            for x in vec:
                if not isinstance(x, (int, float)) or not math.isfinite(float(x)):
                    raise RuntimeError("embeddings: нечисловой вектор")
                fv.append(float(x))
            out.append(_normalize_l2(fv))
        return out

    def _embed_batch(self, texts: list[str], *, interactive: bool) -> list[list[float]]:
        warn_cloud_send_once(_host_from_base_url(self.base_url))
        payload: dict = {
            "model": self.model,
            "input": texts,
            "encoding_format": "float",
        }
        if self.send_dimensions:
            payload["dimensions"] = self.dims
        data = self._post(
            payload,
            timeout=self.query_timeout if interactive else self.timeout,
            max_retries=self.query_max_retries if interactive else self.max_retries,
        )
        return self._parse_vectors(data, len(texts))

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        batch: list[str] = []
        tok_sum = 0
        for text in texts:
            t = estimate_tokens(text)
            if batch and (len(batch) >= self.batch_size or tok_sum + t > self.max_batch_tokens):
                out.extend(self._embed_batch(batch, interactive=False))
                batch, tok_sum = [], 0
            batch.append(text)
            tok_sum += t
        if batch:
            out.extend(self._embed_batch(batch, interactive=False))
        return out

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([text], interactive=True)[0]


@dataclass
class LocalEmbeddingProvider:
    model_path: str
    profile: str
    device: str
    dims: int = 768
    max_input_tokens: int = 512
    _model: object = None

    @property
    def space(self) -> str:
        name = os.path.basename(self.model_path.rstrip("/"))
        if self.profile == "bge-m3":
            return "local:bge-m3"
        if self.profile == "e5" or "e5" in name:
            return "local:multilingual-e5-base"
        return f"local:{name}"

    def describe(self) -> dict:
        return {
            "kind": "local",
            "model": os.path.basename(self.model_path.rstrip("/")),
            "dims": self.dims,
            "host": "local",
        }

    def _load(self):
        if self._model is not None:
            return
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError("не установлен sentence-transformers") from e
        self._model = SentenceTransformer(self.model_path, device=self.device, local_files_only=True)
        dim = self._model.get_sentence_embedding_dimension()
        if dim:
            self.dims = int(dim)

    def _prefix_passage(self, t: str) -> str:
        if self.profile == "e5":
            return f"passage: {t}"
        return t

    def _prefix_query(self, t: str) -> str:
        if self.profile == "e5":
            return f"query: {t}"
        return t

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        self._load()
        inp = [self._prefix_passage(t) for t in texts]
        vecs = self._model.encode(inp, normalize_embeddings=True)
        return [list(map(float, v)) for v in vecs]

    def embed_query(self, text: str) -> list[float]:
        self._load()
        v = self._model.encode([self._prefix_query(text)], normalize_embeddings=True)[0]
        return list(map(float, v))


def _detect_local_profile(path: str) -> str:
    explicit = os.environ.get("EMBED_LOCAL_PROFILE", "").strip().lower()
    if explicit in ("e5", "bge-m3", "generic"):
        return explicit
    base = os.path.basename(path.rstrip("/")).lower()
    if "bge" in base and "m3" in base:
        return "bge-m3"
    if "e5" in base:
        return "e5"
    return "generic"


def resolve_provider(env: dict | None = None) -> tuple[EmbeddingProvider | None, list[str]]:
    """Единственная точка выбора провайдера (§2.2). Без HTTP при none/шаг 4."""
    e = env if env is not None else os.environ
    warnings: list[str] = []
    prov = (e.get("EMBED_PROVIDER") or "auto").strip().lower()

    if prov == "none":
        warnings.append("векторный поиск отключён явно (EMBED_PROVIDER=none)")
        return None, warnings

    if prov == "fake":
        if e.get("PYTEST_CURRENT_TEST") is None and e.get("EMBED_PROVIDER") == "fake":
            warnings.append("fake-эмбеддер: результаты не семантические")
        return FakeEmbeddingProvider(), warnings

    local_reason = ""
    local_provider: EmbeddingProvider | None = None
    if prov == "local":
        path = e.get("EMBED_LOCAL_MODEL", "").strip()
        if not path or not os.path.isdir(path):
            local_reason = "каталог EMBED_LOCAL_MODEL не найден"
        else:
            try:
                local_provider = LocalEmbeddingProvider(
                    model_path=path,
                    profile=_detect_local_profile(path),
                    device=e.get("EMBED_LOCAL_DEVICE", "cpu"),
                )
            except Exception as ex:
                local_reason = str(ex)

    if local_provider is not None:
        return local_provider, warnings

    if prov == "local" and local_reason:
        strict = e.get("EMBED_STRICT_LOCAL", "").strip() == "1"
        api_key = load_env_secret("EMBED_API_KEY")
        if strict or not api_key:
            if strict:
                warnings.append(
                    f"локальная модель объявлена, но недоступна ({local_reason}); "
                    "EMBED_STRICT_LOCAL=1 — облако не используется"
                )
            else:
                warnings.append(
                    "векторный поиск выключен: не задан EMBED_API_KEY и локальная модель недоступна. "
                    "Работает только полнотекстовый поиск."
                )
            return None, warnings
        host = _host_from_base_url(e.get("EMBED_BASE_URL", "https://api.openai.com/v1"))
        warnings.append(
            f"локальная модель объявлена, но недоступна ({local_reason}); "
            f"используется облачный провайдер {host} — текст будет отправлен во внешний API"
        )

    api_key = load_env_secret("EMBED_API_KEY")
    auto_cloud = prov in ("auto", "cloud", "")
    if api_key and (auto_cloud or (prov == "local" and local_reason)):
        model = e.get("EMBED_MODEL", DEFAULT_CLOUD_MODEL)
        return (
            CloudEmbeddingProvider(
                api_key=api_key,
                base_url=e.get("EMBED_BASE_URL", "https://api.openai.com/v1"),
                model=model,
                dims=_env_int("EMBED_DIMS", 768),
                send_dimensions=e.get("EMBED_SEND_DIMENSIONS", "1") != "0",
                batch_size=_env_int("EMBED_BATCH", 64),
                max_batch_tokens=_env_int("EMBED_MAX_BATCH_TOKENS", 100_000),
                timeout=float(e.get("EMBED_TIMEOUT", "30")),
                max_retries=_env_int("EMBED_MAX_RETRIES", 5),
                query_timeout=float(e.get("EMBED_QUERY_TIMEOUT", "5")),
            ),
            warnings,
        )

    warnings.append(
        "векторный поиск выключен: не задан EMBED_API_KEY и не объявлена локальная модель "
        "(EMBED_PROVIDER=local + EMBED_LOCAL_MODEL). Работает только полнотекстовый поиск."
    )
    return None, warnings


def min_similarity_for_space(space: str) -> float:
    raw = os.environ.get("EMBED_MIN_SIM", "")
    if raw:
        try:
            m = json.loads(raw)
            if isinstance(m, dict) and space in m:
                return float(m[space])
        except json.JSONDecodeError:
            pass
        try:
            return float(raw)
        except ValueError:
            pass
    # консервативно, не откалибровано
    if space.startswith("fake:"):
        return 0.35
    return 0.72
