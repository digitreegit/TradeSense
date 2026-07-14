"""Alpaca credentials: env vars with optional dashboard overrides in blob store."""
from __future__ import annotations

from .config import settings
from .state import store

CONFIG_KEY = "alpaca_config"


def get_stored_config() -> dict:
    return store.get(CONFIG_KEY, {})


def get_credentials() -> tuple[str, str, bool]:
    """Return (api_key, secret_key, paper)."""
    stored = get_stored_config()
    api_key = (stored.get("api_key") or settings.alpaca_api_key or "").strip()
    secret_key = (stored.get("secret_key") or settings.alpaca_secret_key or "").strip()
    if stored.get("trading_mode"):
        paper = stored["trading_mode"].lower() != "live"
    else:
        paper = not settings.is_live
    return api_key, secret_key, paper


def get_trading_mode() -> str:
    _, _, paper = get_credentials()
    return "paper" if paper else "live"


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


def save_keys(api_key: str, secret_key: str) -> None:
    stored = get_stored_config()
    stored["api_key"] = api_key.strip()
    stored["secret_key"] = secret_key.strip()
    store.set(CONFIG_KEY, stored)


def clear_keys() -> None:
    stored = get_stored_config()
    stored.pop("api_key", None)
    stored.pop("secret_key", None)
    store.set(CONFIG_KEY, stored)


def set_trading_mode(mode: str) -> None:
    stored = get_stored_config()
    stored["trading_mode"] = "live" if mode.lower() == "live" else "paper"
    store.set(CONFIG_KEY, stored)


def test_connection() -> dict:
    api_key, secret_key, paper = get_credentials()
    if not api_key or not secret_key:
        return {"connected": False, "error": "keys_not_configured"}
    try:
        from alpaca.trading.client import TradingClient

        client = TradingClient(api_key, secret_key, paper=paper)
        acc = client.get_account()
        return {
            "connected": True,
            "paper_trading": paper,
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
    api_key, _, paper = get_credentials()
    configured = is_configured()
    conn = test_connection() if configured else {"connected": False, "error": "keys_not_configured"}
    env_keys = bool(settings.alpaca_api_key and settings.alpaca_secret_key)
    return {
        "configured": configured,
        "keys_source": "dashboard" if keys_from_dashboard() else ("env" if env_keys else "none"),
        "trading_mode": "paper" if paper else "live",
        "paper_trading": paper,
        "key_hint": mask_key(api_key) if configured else "",
        "connection": conn,
    }
