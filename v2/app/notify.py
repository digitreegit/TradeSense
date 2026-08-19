"""Telegram notifications (optional — silently no-ops without credentials)."""
from __future__ import annotations

import logging

import httpx

from .config import settings

log = logging.getLogger(__name__)


def send(text: str) -> bool:
    """Send a plain-text Telegram message. Returns True on success."""
    if not settings.telegram_bot_token:
        log.warning("telegram send skipped: TELEGRAM_BOT_TOKEN not set")
        return False
    if not settings.telegram_chat_id:
        log.warning("telegram send skipped: TELEGRAM_CHAT_ID not set")
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": text},
            timeout=10,
        )
        body = r.json()
        if not body.get("ok"):
            log.warning(
                "telegram send rejected: %s",
                body.get("description", r.text[:200]),
            )
            return False
        return True
    except Exception as exc:
        log.warning("telegram send failed: %s", exc)
        return False


def send_test() -> dict:
    """Diagnostic send with explicit result (the settings panel test button)."""
    if not settings.telegram_bot_token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN이 설정되지 않았습니다."}
    if not settings.telegram_chat_id:
        return {"ok": False, "error": "TELEGRAM_CHAT_ID가 설정되지 않았습니다."}
    ok = send("✅ TradeSense 텔레그램 테스트 — 알림이 정상 작동합니다.")
    if ok:
        return {"ok": True}
    return {"ok": False, "error": "Telegram API가 메시지를 거부했습니다. Vercel 로그를 확인하세요."}
