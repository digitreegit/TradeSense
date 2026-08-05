"""FastAPI dependencies: Supabase bearer token + per-user trading engine."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import users_db
from app.services.supabase_auth import verify_supabase_bearer
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
        payload = verify_supabase_bearer(token)
        email = str(payload.get("email") or "").strip().lower()
        sub = str(payload.get("sub") or "").strip()
        if not email or not sub:
            return None
        users_db.init_db()
        row = users_db.ensure_user_for_supabase(email=email, supabase_user_id=sub)
        return int(row["id"])
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
