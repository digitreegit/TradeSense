"""Alpaca credentials: env vars with optional dashboard overrides in blob store.

Live trading only. Paper mode was removed so a lost/blank stored config can
never silently downgrade a live account to the paper API.
"""
from __future__ import annotations

from .config import settings
from .state import store

CONFIG_KEY = "alpaca_config"

# Alpaca live keys start with AK, paper keys with PK.
LIVE_KEY_PREFIX = "AK"
PAPER_KEY_PREFIX = "PK"


def get_stored_config() -> dict:
    cfg = store.config_get() or {}
    if not cfg.get("api_key"):
        # Migration: keys saved before the dedicated config doc existed.
        legacy = store.get(CONFIG_KEY, {}) or {}
        if legacy.get("api_key"):
            return legacy
    return cfg


def get_credentials() -> tuple[str, str, bool]:
    """Return (api_key, secret_key, paper). Paper is always False."""
    stored = get_stored_config()
    api_key = (stored.get("api_key") or "").strip()
    secret_key = (stored.get("secret_key") or "").strip()
    # A leftover paper pair in the store must not shadow live env keys.
    if is_paper_key(api_key):
        api_key = secret_key = ""
    if not (api_key and secret_key):
        api_key = (settings.alpaca_api_key or "").strip()
        secret_key = (settings.alpaca_secret_key or "").strip()
    return api_key, secret_key, False


def get_trading_mode() -> str:
    return "live"


def is_configured() -> bool:
    api_key, secret_key, _ = get_credentials()
    return bool(api_key and secret_key)


def keys_from_dashboard() -> bool:
    stored = get_stored_config()
    return bool(stored.get("api_key") and stored.get("secret_key"))


def mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return "••••"
    return f"{key[:4]}…{key[-4:]}"


def is_paper_key(api_key: str) -> bool:
    return (api_key or "").strip()[:2].upper() == PAPER_KEY_PREFIX


def save_keys(api_key: str, secret_key: str) -> None:
    api_key = api_key.strip()
    secret_key = secret_key.strip()
    if is_paper_key(api_key):
        raise ValueError(
            "페이퍼 키(PK…)는 사용할 수 없습니다. 라이브 키(AK…)를 입력하세요."
        )
    stored = get_stored_config()
    stored["api_key"] = api_key
    stored["secret_key"] = secret_key
    stored["trading_mode"] = "live"
    store.config_set(stored)


def clear_keys() -> None:
    stored = get_stored_config()
    stored.pop("api_key", None)
    stored.pop("secret_key", None)
    store.config_set(stored)


def test_connection() -> dict:
    api_key, secret_key, paper = get_credentials()
    if not api_key or not secret_key:
        return {"connected": False, "error": "keys_not_configured"}
    if is_paper_key(api_key):
        return {"connected": False, "error": "paper_key_not_allowed"}
    try:
        from alpaca.trading.client import TradingClient

        client = TradingClient(api_key, secret_key, paper=paper)
        acc = client.get_account()
        return {
            "connected": True,
            "paper_trading": False,
            "account": {
                "equity": float(acc.equity),
                "cash": float(acc.cash),
                "buying_power": float(acc.buying_power),
                "portfolio_value": float(acc.portfolio_value),
                "status": str(acc.status),
            },
        }
    except Exception as exc:
        return {"connected": False, "error": str(exc)}


def status_dict() -> dict:
    api_key, _, _ = get_credentials()
    configured = is_configured()
    conn = test_connection() if configured else {"connected": False, "error": "keys_not_configured"}
    env_keys = bool(settings.alpaca_api_key and settings.alpaca_secret_key)
    return {
        "configured": configured,
        "keys_source": "dashboard" if keys_from_dashboard() else ("env" if env_keys else "none"),
        "trading_mode": "live",
        "paper_trading": False,
        "key_hint": mask_key(api_key) if configured else "",
        "key_prefix": api_key[:2].upper() if api_key else "",
        "paper_key_detected": is_paper_key(api_key),
        "connection": conn,
    }
