"""Token encryption at rest.

Fernet (AES-128-CBC + HMAC). Key comes from `Settings.fernet_key`.
Ciphertext goes into `connector_credentials.access_token_enc` / `refresh_token_enc`.

SCALE: rotate keys via a key-id prefix in the ciphertext + a small key
registry. For real production move ciphertext to a KMS-backed secrets
manager and store only a key reference in PG.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class CryptoError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _cipher() -> Fernet:
    s = get_settings()
    if not s.fernet_key or s.fernet_key.startswith("REPLACE_ME"):
        raise CryptoError(
            "FERNET_KEY is not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(s.fernet_key.encode())
    except Exception as e:  # noqa: BLE001
        raise CryptoError(f"invalid FERNET_KEY: {e}") from e


def encrypt(plaintext: str) -> bytes:
    return _cipher().encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    try:
        return _cipher().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as e:
        raise CryptoError("decrypt failed: token invalid (wrong key or tampered)") from e
