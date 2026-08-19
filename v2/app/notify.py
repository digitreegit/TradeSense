"""Telegram notifications (optional — silently no-ops without credentials)."""
from __future__ import annotations

import logging

import httpx

from .config import settings

log = logging.getLogger(__name__)


def _token() -> str:
    return (settings.telegram_bot_token or "").strip()


def _chat_id() -> str:
    return (settings.telegram_chat_id or "").strip()


def telegram_status() -> dict:
    """Safe diagnostics for the settings panel (no secrets)."""
    token = _token()
    chat = _chat_id()
    return {
        "configured": bool(token and chat),
        "token_set": bool(token),
        "chat_id_set": bool(chat),
        "token_hint": f"{token[:4]}…{token[-4:]}" if len(token) >= 10 else "",
        "chat_id_hint": f"…{chat[-4:]}" if len(chat) >= 4 else "",
        "expected_chat_id_suffix": "0870",
    }


def send(text: str) -> bool:
    """Send a plain-text Telegram message. Returns True on success."""
    token, chat = _token(), _chat_id()
    if not token:
        log.warning("telegram send skipped: TELEGRAM_BOT_TOKEN not set")
        return False
    if not chat:
        log.warning("telegram send skipped: TELEGRAM_CHAT_ID not set")
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": str(chat), "text": text},
            timeout=15.0,
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
    status = telegram_status()
    if not status["token_set"]:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.", **status}
    if not status["chat_id_set"]:
        return {"ok": False, "error": "TELEGRAM_CHAT_ID가 설정되지 않았습니다.", **status}

    token, chat = _token(), _chat_id()
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": str(chat),
                "text": "✅ TradeSense 텔레그램 테스트 — 알림이 정상 작동합니다.",
            },
            timeout=15.0,
        )
        body = r.json()
        if body.get("ok"):
            return {
                "ok": True,
                "message": f"발송 성공 — chat …{chat[-4:]} 로 전송됨. 텔레그램 앱을 확인하세요.",
                **status,
            }
        desc = body.get("description", r.text[:200])
        hint = ""
        if "chat not found" in desc.lower():
            hint = f" Vercel TELEGRAM_CHAT_ID가 틀렸습니다. 올바른 값: 8788110870"
        elif "bot was blocked" in desc.lower():
            hint = " @TradeSenseDigtreeBot 을 열고 Start(시작)를 눌러주세요."
        return {
            "ok": False,
            "error": f"Telegram 오류: {desc}.{hint}",
            **status,
        }
    except Exception as exc:
        return {"ok": False, "error": f"전송 실패: {exc}", **status}
