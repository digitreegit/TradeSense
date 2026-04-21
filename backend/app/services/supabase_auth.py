"""Verify Supabase access tokens using project JWKS."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import jwt


def _supabase_url() -> str:
    return os.getenv("SUPABASE_URL", "").strip().rstrip("/")


def _jwt_issuer() -> str:
    base = _supabase_url()
    return f"{base}/auth/v1" if base else ""


def _jwt_audience() -> str:
    return os.getenv("SUPABASE_JWT_AUD", "authenticated").strip() or "authenticated"


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    issuer = _jwt_issuer()
    if not issuer:
        raise RuntimeError("SUPABASE_URL is not configured")
    return jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json")


def decode_supabase_token(token: str) -> dict[str, Any]:
    """Return verified JWT payload from Supabase access token."""
    signing_key = _jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=_jwt_audience(),
        issuer=_jwt_issuer(),
    )


def verify_supabase_bearer(token: str) -> dict[str, Any]:
    """Compatibility wrapper used by dependency injection."""
    return decode_supabase_token(token)

