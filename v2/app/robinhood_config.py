"""Robinhood Crypto Trading API credentials + execution mode."""
from __future__ import annotations

from .config import settings
from .state import store

CONFIG_KEY = "robinhood_config"
EXEC_MODE_KEY = "crypto_exec_mode"

# manual = advise only, user trades in app
# semi   = user confirms in TradeSense → API places order
# auto   = scheduled check places pending orders without confirm
EXEC_MODES = ("manual", "semi", "auto")


def get_stored_config() -> dict:
    return store.get(CONFIG_KEY) or {}


def get_credentials() -> tuple[str, str]:
    stored = get_stored_config()
    api_key = (stored.get("api_key") or "").strip()
    private_key = (stored.get("private_key") or "").strip()
    if not (api_key and private_key):
        api_key = (settings.robinhood_api_key or "").strip()
        private_key = (settings.robinhood_private_key or "").strip()
    return api_key, private_key


def is_configured() -> bool:
    api_key, private_key = get_credentials()
    return bool(api_key and private_key)


def keys_from_dashboard() -> bool:
    stored = get_stored_config()
    return bool(stored.get("api_key") and stored.get("private_key"))


def mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return "••••"
    return f"{key[:6]}…{key[-4:]}"


def save_keys(api_key: str, private_key: str) -> None:
    api_key = api_key.strip()
    private_key = private_key.strip()
    if not api_key or not private_key:
        raise ValueError("API Key와 Private Key를 모두 입력하세요.")
    store.set(CONFIG_KEY, {"api_key": api_key, "private_key": private_key})


def clear_keys() -> None:
    store.set(CONFIG_KEY, {})


def get_execution_mode() -> str:
    mode = (store.get(EXEC_MODE_KEY) or "manual").strip().lower()
    return mode if mode in EXEC_MODES else "manual"


def set_execution_mode(mode: str) -> str:
    mode = (mode or "").strip().lower()
    if mode not in EXEC_MODES:
        raise ValueError(f"모드는 {', '.join(EXEC_MODES)} 중 하나여야 합니다.")
    if mode in ("semi", "auto") and not is_configured():
        raise ValueError("API 주문을 쓰려면 Robinhood 키를 먼저 연결하세요.")
    store.set(EXEC_MODE_KEY, mode)
    return mode


def test_connection() -> dict:
    api_key, private_key = get_credentials()
    if not api_key or not private_key:
        return {"connected": False, "error": "keys_not_configured"}
    try:
        from .robinhood_client import RobinhoodCryptoClient

        client = RobinhoodCryptoClient(api_key, private_key)
        account = client.get_account()
        holdings = client.get_all_holdings()
        return {
            "connected": True,
            "account": {
                "account_number": account.get("account_number"),
                "status": account.get("status"),
                "buying_power": float(account.get("buying_power") or 0),
                "currency": account.get("buying_power_currency") or "USD",
            },
            "holdings_count": len(holdings),
        }
    except Exception as exc:
        return {"connected": False, "error": str(exc)}


def status_dict() -> dict:
    api_key, _ = get_credentials()
    configured = is_configured()
    conn = test_connection() if configured else {"connected": False, "error": "keys_not_configured"}
    env_keys = bool(settings.robinhood_api_key and settings.robinhood_private_key)
    return {
        "configured": configured,
        "keys_source": "dashboard" if keys_from_dashboard() else ("env" if env_keys else "none"),
        "key_hint": mask_key(api_key) if configured else "",
        "connection": conn,
        "execution_mode": get_execution_mode(),
        "execution_modes": list(EXEC_MODES),
    }
