"""Telegram notifications (optional — silently no-ops without credentials)."""
from __future__ import annotations

import logging

import httpx

from .config import settings

log = logging.getLogger(__name__)


def send(text: str) -> None:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as exc:
        log.warning("telegram send failed: %s", exc)


def send_test() -> dict:
    """Diagnostic send with explicit result (the settings panel test button)."""
    if not settings.telegram_bot_token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN이 설정되지 않았습니다."}
    if not settings.telegram_chat_id:
        return {"ok": False, "error": "TELEGRAM_CHAT_ID가 설정되지 않았습니다."}
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id,
                  "text": "✅ TradeSense 텔레그램 테스트 — 알림이 정상 작동합니다."},
            timeout=10,
        )
        body = r.json()
        if not body.get("ok"):
            return {"ok": False,
                    "error": f"Telegram 오류: {body.get('description', r.text[:200])}"}
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": f"전송 실패: {exc}"}
