"""
Earnings calendar service.

Trading engines must skip new entries on a name's earnings day to avoid
overnight-style gap risk on intraday scalps. The previous implementation
left ``trading_engine._earnings_today`` unfilled, making
``event_calendar.symbol_is_earnings_today`` a permanent no-op.

This service provides ``earnings_today_map`` which is plug-pluggable:

1. Local override file (always wins): ``EARNINGS_CALENDAR_FILE`` (or
   ``data/earnings.json`` at the repo root). JSON shape:
       {"AAPL": ["2026-05-01"], "NVDA": ["2026-05-22"]}

2. Date-scoped override: ``data/earnings/<YYYY-MM-DD>.json`` shape:
       ["AAPL", "NVDA"]

3. Optional remote feed (Alpaca corporate actions if/when wired). When the
   feed is unavailable or the keys are missing, the service silently falls
   back to the local files — the engine still gets a useful (possibly
   smaller) blacklist instead of an empty dict.

All paths are read-only here; this never writes to disk.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pytz

ET = pytz.timezone("America/New_York")
logger = logging.getLogger(__name__)


def _today_et_iso() -> str:
    return datetime.now(ET).strftime("%Y-%m-%d")


def _repo_root() -> Path:
    """Backend/app/services/earnings_service.py → repo root."""
    return Path(__file__).resolve().parent.parent.parent.parent


def _override_paths(today_iso: str) -> List[Path]:
    out: List[Path] = []
    env_path = os.getenv("EARNINGS_CALENDAR_FILE", "").strip()
    if env_path:
        out.append(Path(env_path).expanduser())
    repo = _repo_root()
    out.append(repo / "data" / "earnings.json")
    out.append(repo / "data" / "earnings" / f"{today_iso}.json")
    return out


def _normalize_symbols(values: Iterable[object]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for v in values:
        s = str(v or "").strip().upper()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _load_override_map(today_iso: str) -> Dict[str, List[str]]:
    """Read whichever override files exist; merge into ``{SYM: [today_iso]}``."""
    merged: Dict[str, List[str]] = {}
    for path in _override_paths(today_iso):
        try:
            if not path.is_file():
                continue
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("earnings: failed to read %s: %s", path, exc)
            continue

        if isinstance(data, list):
            for sym in _normalize_symbols(data):
                merged.setdefault(sym, []).append(today_iso)
        elif isinstance(data, dict):
            for sym_raw, dates in data.items():
                sym = str(sym_raw or "").strip().upper()
                if not sym:
                    continue
                if isinstance(dates, str):
                    dates = [dates]
                for d in dates or []:
                    d_str = str(d).strip()
                    if d_str and d_str.startswith(today_iso):
                        merged.setdefault(sym, []).append(today_iso)
                        break
    return merged


def earnings_today_map(
    symbols: Optional[Iterable[str]] = None,
    *,
    today: Optional[date] = None,
) -> Dict[str, List[str]]:
    """Return ``{SYMBOL: [today_iso]}`` for names that report **today** (ET).

    ``symbols`` is an optional pre-filter so callers can keep the dict small
    (e.g., the active focus universe). When omitted, the full override map
    is returned.
    """
    today_iso = (today.isoformat() if today else _today_et_iso())
    merged = _load_override_map(today_iso)

    if symbols is None:
        return merged

    universe_set = {str(s or "").strip().upper() for s in symbols if s}
    return {sym: dates for sym, dates in merged.items() if sym in universe_set}
