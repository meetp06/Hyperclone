"""Random agent keys + sha256 fingerprints."""

from __future__ import annotations

import hashlib
import secrets

KEY_PREFIX = "pk_"
KEY_BYTES = 32  # ~256 bits of entropy
PREFIX_LEN = 12  # what we store for UI display: "pk_abc12345"


def generate_key() -> tuple[str, str, str]:
    """Return (plaintext, sha256_hex, prefix).

    Plaintext is returned to the caller once and never persisted.
    Hash is what we store + look up at auth time.
    Prefix is `pk_xxxxxxxx` for the UI list.
    """
    body = secrets.token_urlsafe(KEY_BYTES)
    plaintext = f"{KEY_PREFIX}{body}"
    hashed = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    prefix = plaintext[:PREFIX_LEN]
    return plaintext, hashed, prefix


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
