"""FastAPI dependencies: JWT user + per-user trading engine."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.auth_service import decode_token
from app.services.user_runtime import default_engine, get_or_create_engine

security = HTTPBearer(auto_error=False)


def get_token(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[str]:
    if not creds or creds.scheme.lower() != "bearer":
        return None
    return creds.credentials


def get_current_user_id_optional(
    token: Optional[str] = Depends(get_token),
) -> Optional[int]:
    if not token:
        return None
    try:
        payload = decode_token(token)
        return int(payload["sub"])
    except Exception:
        return None


def get_current_user_id(user_id: Optional[int] = Depends(get_current_user_id_optional)) -> int:
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


def get_current_engine(
    user_id: Optional[int] = Depends(get_current_user_id_optional),
):
    """Authenticated → that user's engine; anonymous → legacy env-based engine."""
    if user_id is not None:
        return get_or_create_engine(user_id)
    return default_engine
