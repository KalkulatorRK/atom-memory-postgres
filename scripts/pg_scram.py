"""SCRAM-SHA-256 verifier for PostgreSQL (клиентское хеширование пароля роли)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import stringprep
import unicodedata


def saslprep(password: str) -> str | None:
    """RFC 4013 SASLprep; None → caller uses raw password (как libpq)."""
    if password is None:
        return None
    mapped: list[str] = []
    for ch in password:
        if stringprep.in_table_b1(ch):
            continue
        if stringprep.in_table_c12(ch):
            mapped.append(" ")
        else:
            mapped.append(ch)
    s = unicodedata.normalize("NFKC", "".join(mapped))
    if not s:
        return None
    for ch in s:
        if (
            stringprep.in_table_a1(ch)
            or stringprep.in_table_c12(ch)
            or stringprep.in_table_c21(ch)
            or stringprep.in_table_c22(ch)
            or stringprep.in_table_c3(ch)
            or stringprep.in_table_c4(ch)
            or stringprep.in_table_c5(ch)
            or stringprep.in_table_c6(ch)
            or stringprep.in_table_c7(ch)
            or stringprep.in_table_c8(ch)
            or stringprep.in_table_c9(ch)
        ):
            return None
    return s


def _scram_password_bytes(password: str) -> bytes:
    prepped = saslprep(password)
    material = prepped if prepped is not None else password
    return material.encode("utf-8")


def scram_sha256_password(password: str, iterations: int = 4096) -> str:
    """Строка для PASSWORD 'SCRAM-SHA-256$…' — открытый текст на сервер не уходит."""
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac(
        "sha256", _scram_password_bytes(password), salt, iterations, dklen=32
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
