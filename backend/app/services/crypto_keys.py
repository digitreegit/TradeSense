"""Encrypt/decrypt Alpaca API keys at rest using Fernet."""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    raw = os.getenv("TRADESENSE_SECRET_KEY", "").strip()
    if not raw:
        raise RuntimeError(
            "TRADESENSE_SECRET_KEY is not set. Set a long random string in .env "
            "(used to encrypt stored Alpaca keys)."
        )
    # Derive 32-byte url-safe key from arbitrary secret
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_text(plain: str) -> bytes:
    return _fernet().encrypt(plain.encode("utf-8"))


def decrypt_text(blob: bytes) -> str:
    return _fernet().decrypt(blob).decode("utf-8")
