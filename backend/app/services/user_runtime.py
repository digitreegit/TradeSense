"""
Per-user Alpaca clients, compliance state, and trading engines.

Legacy: when no JWT / first deploy, ``default_engine`` uses env Alpaca keys
(``alpaca_service`` singleton) like before.

Authenticated users: keys stored encrypted in SQLite; each user gets
isolated ``AlpacaService`` + ``ComplianceService`` + ``TradingEngine``
with its own execution-quality log directory (``trade_logs/user_<id>/``).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Optional

from app.db import users_db
from app.services.alpaca_service import AlpacaService, alpaca_service
from app.services.compliance_service import ComplianceService
from app.services.crypto_keys import decrypt_text
from app.services.trading_engine import TradingEngine

logger = logging.getLogger(__name__)

_alpacas: Dict[int, AlpacaService] = {}
_compliances: Dict[int, ComplianceService] = {}
_engines: Dict[int, TradingEngine] = {}

_log_root = Path(os.getenv("TRADESENSE_LOG_DIR", "./trade_logs"))


def _log_dir_for_user(user_id: int) -> Path:
    d = _log_root / f"user_{user_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_alpaca_keys_for_user(user_id: int) -> tuple[str, str]:
    """Return (api_key, secret) or ("", "") if not configured."""
    row = users_db.get_user_by_id(user_id)
    if row and row.get("alpaca_key_enc") and row.get("alpaca_secret_enc"):
        try:
            k = decrypt_text(row["alpaca_key_enc"])
            s = decrypt_text(row["alpaca_secret_enc"])
            return k.strip(), s.strip()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to decrypt Alpaca keys for user %s: %s", user_id, exc)
            return "", ""
    return "", ""


def get_or_create_alpaca(user_id: int) -> AlpacaService:
    if user_id in _alpacas:
        return _alpacas[user_id]
    svc = AlpacaService()
    key, secret = load_alpaca_keys_for_user(user_id)
    if key and secret:
        svc.initialize_with_keys(key, secret)
    else:
        svc.initialize_with_keys("", "")
    _alpacas[user_id] = svc
    return svc


def get_or_create_engine(user_id: int) -> TradingEngine:
    if user_id in _engines:
        row = users_db.get_user_by_id(user_id)
        if row and row.get("email"):
            _engines[user_id].owner_email = str(row["email"]).strip().lower()
        return _engines[user_id]
    alpaca = get_or_create_alpaca(user_id)
    log_dir = _log_dir_for_user(user_id)
    comp = ComplianceService(log_dir=log_dir)
    row = users_db.get_user_by_id(user_id)
    owner_email = str(row["email"]).strip().lower() if row and row.get("email") else None
    eng = TradingEngine(alpaca, comp, owner_email=owner_email, log_dir=log_dir)
    _engines[user_id] = eng
    return eng


def refresh_user_alpaca(user_id: int) -> None:
    """Call after saving new keys in DB."""
    _alpacas.pop(user_id, None)
    if user_id in _engines:
        alpaca = get_or_create_alpaca(user_id)
        log_dir = _log_dir_for_user(user_id)
        comp = ComplianceService(log_dir=log_dir)
        row = users_db.get_user_by_id(user_id)
        owner_email = str(row["email"]).strip().lower() if row and row.get("email") else None
        eng = TradingEngine(alpaca, comp, owner_email=owner_email, log_dir=log_dir)
        _engines[user_id] = eng


# Legacy default (env Alpaca) — same process-wide singleton as before
_compliance_default = ComplianceService(log_dir=_log_root)
default_engine = TradingEngine(alpaca_service, _compliance_default, log_dir=_log_root)


def engines_to_run() -> list[TradingEngine]:
    """All engines that should advance each scan tick.

    If any user has registered an engine (Alpaca keys saved), only those run.
    Otherwise fall back to the legacy single-process engine using ``.env`` keys.
    """
    if _engines:
        return [_engines[uid] for uid in sorted(_engines.keys())]
    return [default_engine]


def warm_registered_users() -> None:
    """Pre-create engines for users with stored Alpaca keys."""
    users_db.init_db()
    try:
        ids = users_db.list_user_ids_with_alpaca()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not list users for engine warm: %s", exc)
        return
    for uid in ids:
        try:
            get_or_create_engine(uid)
            logger.info("Warmed trading engine for user_id=%s", uid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not warm engine for user %s: %s", uid, exc)
