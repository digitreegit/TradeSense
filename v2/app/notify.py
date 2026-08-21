"""Telegram notifications (optional — silently no-ops without credentials)."""
from __future__ import annotations

import logging
import re

import httpx

from .config import settings

log = logging.getLogger(__name__)

_EXPECTED_CHAT_ID = "8788110870"
_BOT_USERNAME = "TradeSenseDigtreeBot"


def _clean_secret(value: str) -> str:
    """Strip whitespace / wrapping quotes that Vercel paste often adds."""
    v = (value or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1].strip()
    # BOM / zero-width leftovers from copy-paste
    v = v.replace("\ufeff", "").replace("\u200b", "")
    return v


def _token() -> str:
    return _clean_secret(settings.telegram_bot_token or "")


def _chat_id() -> str:
    return _clean_secret(settings.telegram_chat_id or "")


def _chat_id_issue(chat: str) -> str | None:
    """Return issue code: placeholder | mismatch | None if OK."""
    if not chat:
        return "missing"
    if "TELEGRAM" in chat.upper() or not chat.lstrip("-").isdigit():
        return "placeholder"
    if chat != _EXPECTED_CHAT_ID and not chat.endswith("0870"):
        return "mismatch"
    return None


def telegram_status() -> dict:
    """Safe diagnostics for the settings panel (no secrets)."""
    token = _token()
    chat = _chat_id()
    issue = _chat_id_issue(chat)
    return {
        "configured": bool(token and chat and issue is None),
        "token_set": bool(token),
        "chat_id_set": bool(chat),
        "token_hint": f"{token[:4]}…{token[-4:]}" if len(token) >= 10 else "",
        "chat_id_hint": f"…{chat[-4:]}" if len(chat) >= 4 else chat,
        "expected_chat_id": _EXPECTED_CHAT_ID,
        "bot_username": _BOT_USERNAME,
        "chat_id_issue": issue,
    }


def _api(token: str, method: str, payload: dict | None = None) -> dict:
    r = httpx.post(
        f"https://api.telegram.org/bot{token}/{method}",
        json=payload or {},
        timeout=20.0,
    )
    try:
        body = r.json()
    except Exception:
        return {"ok": False, "description": f"HTTP {r.status_code}: {r.text[:200]}"}
    if not isinstance(body, dict):
        return {"ok": False, "description": f"unexpected response: {str(body)[:200]}"}
    return body


def _hint_for_error(desc: str) -> str:
    low = (desc or "").lower()
    if "chat not found" in low or "chat_id is empty" in low:
        return (
            f" Vercel TELEGRAM_CHAT_ID를 확인하세요. 올바른 값: {_EXPECTED_CHAT_ID}."
            f" 그리고 @{_BOT_USERNAME} 을 열고 Start(/start)를 한 번 눌러주세요."
        )
    if "bot was blocked" in low or "forbidden" in low or "can't initiate" in low:
        return (
            f" @{_BOT_USERNAME} 채팅을 열고 Start(시작) 또는 /start 를 눌러주세요."
            " 봇에게 먼저 말을 걸어야 메시지를 받을 수 있습니다."
        )
    if "unauthorized" in low:
        return " TELEGRAM_BOT_TOKEN이 잘못됐거나 폐기됐습니다. Vercel에서 토큰을 다시 넣으세요."
    return ""


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
        # Prefer numeric chat_id when possible — Telegram accepts both, but
        # stringified floats / quoted values break delivery.
        payload_chat: str | int = int(chat) if re.fullmatch(r"-?\d+", chat) else chat
        body = _api(token, "sendMessage", {"chat_id": payload_chat, "text": text})
        if not body.get("ok"):
            log.warning(
                "telegram send rejected: %s",
                body.get("description", str(body)[:200]),
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
        me = _api(token, "getMe")
        if not me.get("ok"):
            desc = me.get("description", "getMe failed")
            return {
                "ok": False,
                "error": f"봇 토큰 오류: {desc}.{_hint_for_error(str(desc))}",
                **status,
            }
        bot = (me.get("result") or {}).get("username") or "?"
        status = {**status, "bot_username": bot}

        payload_chat: str | int = int(chat) if re.fullmatch(r"-?\d+", chat) else chat
        body = _api(
            token,
            "sendMessage",
            {
                "chat_id": payload_chat,
                "text": (
                    "✅ TradeSense 텔레그램 테스트 — 알림이 정상 작동합니다.\n"
                    f"봇 @{bot} → chat {chat}"
                ),
            },
        )
        if body.get("ok"):
            return {
                "ok": True,
                "message": (
                    f"발송 성공 — @{bot} 이 chat …{chat[-4:]} 로 전송했습니다. "
                    "텔레그램 앱에서 해당 봇 채팅을 확인하세요."
                ),
                **status,
            }
        desc = str(body.get("description") or body)
        return {
            "ok": False,
            "error": f"Telegram 오류: {desc}.{_hint_for_error(desc)}",
            **status,
        }
    except Exception as exc:
        return {"ok": False, "error": f"전송 실패: {exc}", **status}
