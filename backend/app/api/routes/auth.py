"""Supabase-backed auth + Alpaca key storage (encrypted)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_user_id, get_current_user_id_optional
from app.db import users_db
from app.services.crypto_keys import encrypt_text
from app.services.user_runtime import refresh_user_alpaca

router = APIRouter(prefix="/auth", tags=["auth"])


class AlpacaKeysBody(BaseModel):
    api_key: str = Field(..., min_length=10)
    secret_key: str = Field(..., min_length=10)


@router.get("/me")
async def me(user_id: Optional[int] = Depends(get_current_user_id_optional)):
    if user_id is None:
        return {"authenticated": False}
    row = users_db.get_user_by_id(user_id)
    if not row:
        raise HTTPException(status_code=401, detail="User not found")
    has_alpaca = bool(row.get("alpaca_key_enc") and row.get("alpaca_secret_enc"))
    return {
        "authenticated": True,
        "user_id": user_id,
        "email": row["email"],
        "alpaca_configured": has_alpaca,
    }


@router.post("/alpaca-keys")
async def save_alpaca_keys(body: AlpacaKeysBody, user_id: int = Depends(get_current_user_id)):
    """Store Alpaca paper API keys (encrypted). Trading uses these for this account."""
    try:
        k_enc = encrypt_text(body.api_key.strip())
        s_enc = encrypt_text(body.secret_key.strip())
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    users_db.set_user_alpaca_encrypted(user_id, k_enc, s_enc)
    refresh_user_alpaca(user_id)
    return {"ok": True, "message": "Alpaca keys saved. Reconnect to verify."}


@router.delete("/alpaca-keys")
async def delete_alpaca_keys(user_id: int = Depends(get_current_user_id)):
    """Delete stored Alpaca keys so the user can register a new pair."""
    users_db.clear_user_alpaca_encrypted(user_id)
    refresh_user_alpaca(user_id)
    return {"ok": True, "message": "Alpaca keys deleted."}
