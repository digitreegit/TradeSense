"""Supabase-backed auth + Alpaca key storage (encrypted)."""
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_user_id, get_current_user_id_optional
from app.core.config import settings
from app.db import users_db
from app.services.crypto_keys import encrypt_text
from app.services.notification_service import notification_service
from app.services.user_runtime import refresh_user_alpaca

router = APIRouter(prefix="/auth", tags=["auth"])


def _invitation_codes_allowlist() -> list[str]:
    raw = (settings.invitation_codes or "").strip()
    if not raw:
        return []
    return [c.strip() for c in raw.split(",") if c.strip()]


def _invitation_code_valid(submitted: str) -> bool:
    """Constant-time compare against configured codes."""
    allowed = _invitation_codes_allowlist()
    if not allowed:
        return True
    code = (submitted or "").strip()
    if not code:
        return False
    for a in allowed:
        if len(code) != len(a):
            continue
        if secrets.compare_digest(code, a):
            return True
    return False


class InvitationBody(BaseModel):
    code: str = Field(default="", max_length=512)


@router.post("/validate-invitation")
async def validate_invitation(body: InvitationBody):
    """Require a matching code when INVITATION_CODES is non-empty; otherwise allow."""
    allowed = _invitation_codes_allowlist()
    if not allowed:
        return {"valid": True}
    if not _invitation_code_valid(body.code):
        raise HTTPException(status_code=403, detail="Invalid invitation code")
    return {"valid": True}


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
    paper = users_db.get_alpaca_paper_trading(user_id) if has_alpaca else True
    twilio_configured = bool(
        (settings.twilio_account_sid or "").strip()
        and (settings.twilio_auth_token or "").strip()
        and (settings.twilio_whatsapp_from or "").strip()
    )
    return {
        "authenticated": True,
        "user_id": user_id,
        "email": row["email"],
        "alpaca_configured": has_alpaca,
        "alpaca_paper_trading": paper,
        "notify_telegram": bool(int(row.get("notify_telegram") or 0)),
        "telegram_chat_id": (row.get("telegram_chat_id") or "") or "",
        "telegram_bot_configured": bool((settings.telegram_bot_token or "").strip()),
        "notify_whatsapp": bool(int(row.get("notify_whatsapp") or 0)),
        "whatsapp_e164": (row.get("whatsapp_e164") or "") or "",
        "whatsapp_configured": twilio_configured,
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


class NotificationPrefsBody(BaseModel):
    notify_telegram: bool = False
    telegram_chat_id: str = Field(default="", max_length=64)
    notify_whatsapp: bool = False
    whatsapp_e164: str = Field(default="", max_length=24)


def _notification_prefs_dict(user_id: int) -> dict:
    row = users_db.get_user_by_id(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    twilio_configured = bool(
        (settings.twilio_account_sid or "").strip()
        and (settings.twilio_auth_token or "").strip()
        and (settings.twilio_whatsapp_from or "").strip()
    )
    return {
        "notify_telegram": bool(int(row.get("notify_telegram") or 0)),
        "telegram_chat_id": (row.get("telegram_chat_id") or "") or "",
        "telegram_bot_configured": bool((settings.telegram_bot_token or "").strip()),
        "notify_whatsapp": bool(int(row.get("notify_whatsapp") or 0)),
        "whatsapp_e164": (row.get("whatsapp_e164") or "") or "",
        "whatsapp_configured": twilio_configured,
    }


@router.get("/notification-prefs")
async def get_notification_prefs(user_id: int = Depends(get_current_user_id)):
    return _notification_prefs_dict(user_id)


@router.post("/notification-prefs")
async def set_notification_prefs(
    body: NotificationPrefsBody,
    user_id: int = Depends(get_current_user_id),
):
    users_db.update_user_notification_prefs(
        user_id,
        notify_telegram=body.notify_telegram,
        telegram_chat_id=body.telegram_chat_id,
        notify_whatsapp=body.notify_whatsapp,
        whatsapp_e164=body.whatsapp_e164,
    )
    return _notification_prefs_dict(user_id)


@router.post("/notification-test")
async def test_notification(user_id: int = Depends(get_current_user_id)):
    """Send a short test message; returns explicit error if Telegram rejects or prefs missing."""
    result = notification_service.try_send_telegram_test(user_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Telegram test failed"))
    return {"ok": True, "message": result.get("message", "Delivered.")}


@router.post("/whatsapp-test")
async def test_whatsapp(user_id: int = Depends(get_current_user_id)):
    """Send a short WhatsApp test; explicit error if Twilio rejects or prefs missing."""
    result = notification_service.try_send_whatsapp_test(user_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "WhatsApp test failed"))
    return {"ok": True, "message": result.get("message", "Delivered.")}
