"""SCRAM-SHA-256 verifier for PostgreSQL (клиентское хеширование пароля роли)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


def scram_sha256_password(password: str, iterations: int = 4096) -> str:
    """Строка для PASSWORD 'SCRAM-SHA-256$…' — открытый текст на сервер не уходит."""
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations, dklen=32
    )

    def hmac_sha256(key: bytes, msg: bytes) -> bytes:
        return hmac.new(key, msg, hashlib.sha256).digest()

    client_key = hmac_sha256(salted, b"Client Key")
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac_sha256(salted, b"Server Key")
    salt_b64 = base64.b64encode(salt).decode("ascii")
    sk_b64 = base64.b64encode(stored_key).decode("ascii")
    srv_b64 = base64.b64encode(server_key).decode("ascii")
    return f"SCRAM-SHA-256${iterations}:{salt_b64}${sk_b64}:{srv_b64}"
