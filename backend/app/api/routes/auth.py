"""Supabase-backed auth + Alpaca key storage (encrypted)."""
from __future__ import annotations

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
    return {
        "authenticated": True,
        "user_id": user_id,
        "email": row["email"],
        "alpaca_configured": has_alpaca,
        "alpaca_paper_trading": paper,
        "notify_telegram": bool(int(row.get("notify_telegram") or 0)),
        "telegram_chat_id": (row.get("telegram_chat_id") or "") or "",
        "notify_whatsapp": bool(int(row.get("notify_whatsapp") or 0)),
        "whatsapp_e164": (row.get("whatsapp_e164") or "") or "",
        "telegram_bot_configured": bool((settings.telegram_bot_token or "").strip()),
        "whatsapp_provider_configured": bool(
            (settings.twilio_account_sid or "").strip()
            and (settings.twilio_auth_token or "").strip()
            and (settings.twilio_whatsapp_from or "").strip()
        ),
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
    whatsapp_e164: str = Field(default="", max_length=32)


def _notification_prefs_dict(user_id: int) -> dict:
    row = users_db.get_user_by_id(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "notify_telegram": bool(int(row.get("notify_telegram") or 0)),
        "telegram_chat_id": (row.get("telegram_chat_id") or "") or "",
        "notify_whatsapp": bool(int(row.get("notify_whatsapp") or 0)),
        "whatsapp_e164": (row.get("whatsapp_e164") or "") or "",
        "telegram_bot_configured": bool((settings.telegram_bot_token or "").strip()),
        "whatsapp_provider_configured": bool(
            (settings.twilio_account_sid or "").strip()
            and (settings.twilio_auth_token or "").strip()
            and (settings.twilio_whatsapp_from or "").strip()
        ),
    }


@router.get("/notification-prefs")
async def get_notification_prefs(user_id: int = Depends(get_current_user_id)):
    return _notification_prefs_dict(user_id)


@router.post("/notification-prefs")
async def set_notification_prefs(
    body: NotificationPrefsBody,
    user_id: int = Depends(get_current_user_id),
):
    wa = body.whatsapp_e164.strip()
    if wa and not wa.startswith("+"):
        raise HTTPException(
            status_code=400,
            detail="WhatsApp number must be in E.164 format starting with + (e.g. +14155551234)",
        )
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
    """Send a short test message to enabled Telegram / WhatsApp channels."""
    notification_service.send_alert(
        "TradeSense test",
        "If you received this, your notification settings are working.",
        "INFO",
        to_email="",
        user_id=user_id,
    )
    return {"ok": True, "message": "Test sent (check Telegram / WhatsApp if enabled)."}
