"""Verify Supabase access tokens.

Supabase currently signs access tokens with HS256 using the project's
``JWT Secret``. Newer projects may also expose an asymmetric (RS256/ES256)
key pair via JWKS. This module transparently supports both:

1. If ``SUPABASE_JWT_SECRET`` is configured, verify using HS256.
2. Otherwise fall back to the project's JWKS endpoint (RS256/ES256).

The Supabase project issuer is always ``{SUPABASE_URL}/auth/v1`` and the
default audience is ``authenticated`` (override with ``SUPABASE_JWT_AUD``).
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

import jwt

logger = logging.getLogger(__name__)


def _supabase_url() -> str:
    return os.getenv("SUPABASE_URL", "").strip().rstrip("/")


def _jwt_issuer() -> str:
    base = _supabase_url()
    return f"{base}/auth/v1" if base else ""


def _jwt_audience() -> str:
    return os.getenv("SUPABASE_JWT_AUD", "authenticated").strip() or "authenticated"


def _jwt_secret() -> str:
    return os.getenv("SUPABASE_JWT_SECRET", "").strip()


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    issuer = _jwt_issuer()
    if not issuer:
        raise RuntimeError("SUPABASE_URL is not configured")
    return jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json")


def _decode_hs256(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        _jwt_secret(),
        algorithms=["HS256"],
        audience=_jwt_audience(),
        issuer=_jwt_issuer(),
    )


def _decode_asymmetric(token: str) -> dict[str, Any]:
    header = jwt.get_unverified_header(token)
    algorithm = header.get("alg") or "RS256"
    signing_key = _jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=[algorithm],
        audience=_jwt_audience(),
        issuer=_jwt_issuer(),
    )


def decode_supabase_token(token: str) -> dict[str, Any]:
    """Return verified JWT payload from a Supabase access token.

    Tries HS256 first when a project JWT secret is configured (the default
    for Supabase projects today), then falls back to JWKS-based verification
    for projects that have migrated to asymmetric signing keys.
    """
    if not _supabase_url():
        raise RuntimeError("SUPABASE_URL is not configured")

    header = jwt.get_unverified_header(token)
    algorithm = (header.get("alg") or "").upper()

    if algorithm == "HS256":
        secret = _jwt_secret()
        if not secret:
            raise RuntimeError(
                "SUPABASE_JWT_SECRET is required to verify HS256 tokens. "
                "Copy it from Supabase Dashboard → Project Settings → API → JWT Secret."
            )
        return _decode_hs256(token)

    # Asymmetric (RS256/ES256) — verify via project JWKS.
    return _decode_asymmetric(token)


def verify_supabase_bearer(token: str) -> dict[str, Any]:
    """Compatibility wrapper used by FastAPI dependencies."""
    return decode_supabase_token(token)
