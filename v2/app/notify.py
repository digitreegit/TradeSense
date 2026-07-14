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
