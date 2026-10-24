from __future__ import annotations

import hashlib
import hmac
import os
import secrets


DEFAULT_PASSWORD_ITERATIONS = 180_000


def _iterations() -> int:
    value = int(os.getenv("PASSWORD_HASH_ITERATIONS", str(DEFAULT_PASSWORD_ITERATIONS)))
    return max(1_000, value)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = _iterations()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(raw_iterations),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def random_token() -> str:
    return secrets.token_urlsafe(32)
