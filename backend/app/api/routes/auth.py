"""Sign up / Sign in + Alpaca key storage (encrypted)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import get_current_user_id, get_current_user_id_optional
from app.db import users_db
from app.services.auth_service import login_user, register_user
from app.services.crypto_keys import encrypt_text
from app.services.user_runtime import refresh_user_alpaca

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class AlpacaKeysBody(BaseModel):
    api_key: str = Field(..., min_length=10)
    secret_key: str = Field(..., min_length=10)


@router.post("/register")
async def register(body: RegisterBody):
    users_db.init_db()
    try:
        return register_user(body.email, body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/login")
async def login(body: LoginBody):
    users_db.init_db()
    try:
        return login_user(body.email, body.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


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
