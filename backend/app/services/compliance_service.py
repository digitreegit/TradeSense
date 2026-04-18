"""
Cash-account compliance tracking: GFV / free-riding + short-term tax logs.

The trading engine calls these hooks on every buy / sell. State is kept
in-memory (fine for a single-process micro-scalper). Persist to disk /
SQLite later if you need restart-resilience.
"""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pytz

ET = pytz.timezone("America/New_York")
logger = logging.getLogger(__name__)

# Settlement for US equities is T+1 as of 2024-05-28 (SEC Release 34-96930).
SETTLE_DAYS = 1


def _today_et() -> date:
    return datetime.now(ET).date()


def _next_business_day(d: date, days: int = 1) -> date:
    out = d
    added = 0
    while added < days:
        out = out + timedelta(days=1)
        if out.weekday() < 5:  # Mon..Fri
            added += 1
    return out


class UnsettledLot:
    __slots__ = ("symbol", "qty", "cost", "bought_on", "settles_on", "used_unsettled")

    def __init__(self, symbol: str, qty: int, cost: float, used_unsettled: bool):
        self.symbol = symbol
        self.qty = qty
        self.cost = cost
        self.bought_on = _today_et()
        self.settles_on = _next_business_day(self.bought_on, SETTLE_DAYS)
        self.used_unsettled = used_unsettled


class ComplianceService:
    """
    GFV (Good Faith Violation) & free-riding tracker for cash accounts.

    Rules enforced:

    1. ``record_buy`` tags the lot with whether it consumed *unsettled* cash.
    2. ``can_sell`` returns False for lots still unsettled that were bought
       with unsettled proceeds — selling them would be a GFV.
    3. ``gfv_count`` exposes rolling 12-month GFV counter; 3 in 12 months ⇒
       Alpaca restricts the account to settled funds for 90 days.
    4. ``log_trade`` persists realized P&L for tax season (short-term,
       wash-sale candidates flagged).
    """

    def __init__(self, log_dir: Optional[Path] = None):
        self._unsettled_cash: float = 0.0
        self._lots: List[UnsettledLot] = []
        self._gfv_events: List[date] = []
        self._wash_sale_cooldown: Dict[str, date] = {}
        self._realized: List[dict] = []
        self._loss_streak: int = 0
        self._cooldown_until: Optional[datetime] = None

        self._log_dir = log_dir or Path(os.getenv("TRADESENSE_LOG_DIR", "./trade_logs"))
        self._log_dir.mkdir(parents=True, exist_ok=True)

    # ─── Settlement ──────────────────────────────────────────────
    def sweep_settlements(self) -> None:
        """Move lots past their settles_on to 'settled' (removed from tracker)."""
        today = _today_et()
        still_unsettled = []
        for lot in self._lots:
            if lot.settles_on <= today:
                continue  # now settled, drop it
            still_unsettled.append(lot)
        self._lots = still_unsettled

        # Unsettled cash decays when the oldest sells settle.
        # Caller records _unsettled_cash on sells; we just reset on new day here.
        if self._unsettled_cash < 0:
            self._unsettled_cash = 0.0

    # ─── Buy / sell hooks ───────────────────────────────────────
    def settled_cash(self, total_cash: float) -> float:
        return max(total_cash - self._unsettled_cash, 0.0)

    def record_buy(self, symbol: str, qty: int, price: float, settled_before: float) -> None:
        cost = qty * price
        used_unsettled = cost > settled_before + 1e-6
        lot = UnsettledLot(symbol, qty, cost, used_unsettled)
        self._lots.append(lot)
        if used_unsettled:
            logger.info(
                "compliance: %s bought with unsettled cash (cost=$%.2f, settled=$%.2f)",
                symbol, cost, settled_before,
            )

    def record_sell(self, symbol: str, qty: int, price: float, cost_basis: float) -> None:
        """Record a sell. Proceeds go into unsettled cash for T+1."""
        proceeds = qty * price
        self._unsettled_cash += proceeds

        pnl = proceeds - cost_basis
        self._realized.append(
            {
                "time": datetime.now(ET).isoformat(),
                "symbol": symbol,
                "qty": qty,
                "proceeds": round(proceeds, 2),
                "cost_basis": round(cost_basis, 2),
                "pnl": round(pnl, 2),
                "hold_term": "short",
            }
        )
        self._persist_realized()

        if pnl < 0:
            # Wash-sale watch: block re-entry in same symbol for 30 days
            self._wash_sale_cooldown[symbol] = _today_et() + timedelta(days=30)
            self._loss_streak += 1
        else:
            self._loss_streak = 0

        # Detect GFV: selling a lot that was bought with unsettled cash
        # before settlement.
        today = _today_et()
        for lot in self._lots:
            if lot.symbol != symbol:
                continue
            if lot.used_unsettled and lot.settles_on > today:
                self._gfv_events.append(today)
                logger.warning(
                    "compliance: GFV on %s — sold unsettled lot (settles %s)",
                    symbol, lot.settles_on,
                )

    def can_sell(self, symbol: str) -> bool:
        today = _today_et()
        for lot in self._lots:
            if lot.symbol == symbol and lot.used_unsettled and lot.settles_on > today:
                return False
        return True

    def can_enter(self, symbol: str) -> Optional[str]:
        """Return reason string to block a buy, or None if OK."""
        until = self._wash_sale_cooldown.get(symbol)
        if until and until > _today_et():
            return f"wash-sale cooldown until {until}"
        return None

    # ─── Cooldowns / circuit breaker ─────────────────────────────
    def register_loss_streak_cooldown(self, minutes: int = 15) -> None:
        """Pause new entries after N consecutive losses."""
        self._cooldown_until = datetime.now(ET) + timedelta(minutes=minutes)

    @property
    def loss_streak(self) -> int:
        return self._loss_streak

    def is_cooling_down(self) -> bool:
        if not self._cooldown_until:
            return False
        return datetime.now(ET) < self._cooldown_until

    def cooldown_remaining_s(self) -> int:
        if not self._cooldown_until:
            return 0
        delta = (self._cooldown_until - datetime.now(ET)).total_seconds()
        return max(0, int(delta))

    # ─── GFV reporting ──────────────────────────────────────────
    @property
    def gfv_count_12mo(self) -> int:
        cutoff = _today_et() - timedelta(days=365)
        return sum(1 for d in self._gfv_events if d >= cutoff)

    def gfv_warning_level(self) -> str:
        n = self.gfv_count_12mo
        if n >= 3:
            return "RESTRICTED"
        if n == 2:
            return "WARNING"
        if n == 1:
            return "NOTICE"
        return "OK"

    def status(self) -> dict:
        return {
            "unsettled_cash": round(self._unsettled_cash, 2),
            "open_unsettled_lots": len(self._lots),
            "gfv_count_12mo": self.gfv_count_12mo,
            "gfv_level": self.gfv_warning_level(),
            "loss_streak": self._loss_streak,
            "cooling_down": self.is_cooling_down(),
            "cooldown_remaining_s": self.cooldown_remaining_s(),
            "wash_sale_cooldowns": {
                s: d.isoformat() for s, d in self._wash_sale_cooldown.items()
            },
        }

    # ─── Persistence ────────────────────────────────────────────
    def _persist_realized(self) -> None:
        try:
            today = _today_et()
            path = self._log_dir / f"trades-{today.isoformat()}.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(self._realized[-1]) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("compliance: failed to persist trade log: %s", exc)


compliance_service = ComplianceService()
