from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

AUTH_HASH_PREFIX = "pbkdf2_sha256"
AUTH_HASH_ITERATIONS = 260_000
AUTH_HASH_SALT_BYTES = 16


def _clean_secret(value: object) -> str:
    return str(value or "").strip()


def is_hashed_auth_secret(value: object) -> bool:
    return _clean_secret(value).startswith(f"{AUTH_HASH_PREFIX}$")


def hash_auth_secret(secret: str, *, salt: bytes | None = None) -> str:
    normalized = _clean_secret(secret)
    if not normalized:
        raise ValueError("auth secret is required")
    salt_bytes = salt or os.urandom(AUTH_HASH_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        normalized.encode("utf-8"),
        salt_bytes,
        AUTH_HASH_ITERATIONS,
    )
    return f"{AUTH_HASH_PREFIX}${AUTH_HASH_ITERATIONS}${salt_bytes.hex()}${digest.hex()}"


def verify_auth_secret(secret: str, stored_value: object) -> bool:
    normalized = _clean_secret(secret)
    stored = _clean_secret(stored_value)
    if not normalized or not stored:
        return False
    if not is_hashed_auth_secret(stored):
        return hmac.compare_digest(normalized, stored)
    try:
        _, iterations_text, salt_hex, digest_hex = stored.split("$", 3)
        expected = hashlib.pbkdf2_hmac(
            "sha256",
            normalized.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations_text),
        ).hex()
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(expected, digest_hex)


def build_signed_token(payload: dict[str, object], secret: str) -> str:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def read_signed_token(token: str, secret: str) -> dict[str, object] | None:
    encoded, separator, signature = str(token or "").partition(".")
    if not separator or not encoded or not signature:
        return None
    expected = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
