"""
Cash-account compliance tracking: GFV / free-riding + T+1 proceeds + tax lots.

- **T+1 settlement** (SEC 34-96930, 2024-05-28): sell proceeds are modelled as
  unavailable until the settlement date; ``settled_cash()`` subtracts only
  *still-unsettled* pending sale amounts (not a monotonic lump sum).

- **Tax lots (FIFO)**: each buy opens a lot with a stable ``lot_id``. Sells
  close lots first-in-first-out so realized P/L and wash-sale candidates are
  logged per closed lot.

State is in-memory; JSONL under ``TRADESENSE_LOG_DIR`` for realized trades
and wash-sale analytics.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz

ET = pytz.timezone("America/New_York")
logger = logging.getLogger(__name__)

# Settlement for US equities is T+1 as of 2024-05-28 (SEC Release 34-96930).
SETTLE_DAYS = 1
WASH_SALE_LOOKBACK_DAYS = 30


def _today_et() -> date:
    return datetime.now(ET).date()


def _next_business_day(d: date, days: int = 1) -> date:
    out = d
    added = 0
    while added < days:
        out = out + timedelta(days=1)
        if out.weekday() < 5:
            added += 1
    return out


@dataclass
class TaxLot:
    """Open long lot (cash account)."""

    lot_id: str
    symbol: str
    qty: int
    unit_cost: float
    total_cost: float
    bought_on: date
    settles_on: date
    used_unsettled: bool


@dataclass
class PendingSaleSettlement:
    """Sell proceeds not yet settled (T+1)."""

    proceeds: float
    settles_on: date


class ComplianceService:
    """
    GFV tracker + T+1 pending proceeds + FIFO tax lots + wash-sale logging.

    ``record_buy`` opens a tax lot. ``record_sell`` closes lots FIFO, books
    pending settlement for proceeds, logs wash-sale *candidates* per closed
    lot on losses, and enforces a conservative re-entry cooldown per symbol.
    """

    def __init__(self, log_dir: Optional[Path] = None):
        self._tax_lots: List[TaxLot] = []
        self._pending_sales: List[PendingSaleSettlement] = []
        self._gfv_events: List[date] = []
        self._wash_sale_cooldown: Dict[str, date] = {}
        self._realized: List[dict] = []
        self._loss_streak: int = 0
        self._cooldown_until: Optional[datetime] = None

        self._log_dir = log_dir or Path(os.getenv("TRADESENSE_LOG_DIR", "./trade_logs"))
        self._log_dir.mkdir(parents=True, exist_ok=True)

    # ─── T+1 pending proceeds ───────────────────────────────────
    def _pending_sale_proceeds_unsettled(self) -> float:
        today = _today_et()
        return sum(p.proceeds for p in self._pending_sales if p.settles_on > today)

    def settled_cash(self, total_cash: float) -> float:
        """Broker cash minus sell proceeds still inside T+1 settlement."""
        return max(total_cash - self._pending_sale_proceeds_unsettled(), 0.0)

    def sweep_settlements(self) -> None:
        """Release T+1 sale proceeds past settlement; clear GFV flags on settled buys."""
        today = _today_et()
        self._pending_sales = [p for p in self._pending_sales if p.settles_on > today]
        for lot in self._tax_lots:
            if lot.settles_on <= today:
                lot.used_unsettled = False

    # ─── Buy / sell hooks ───────────────────────────────────────
    def record_buy(self, symbol: str, qty: int, price: float, settled_before: float) -> None:
        sym = symbol.upper()
        cost = qty * price
        used_unsettled = cost > settled_before + 1e-6
        lot_id = uuid.uuid4().hex[:12]
        lot = TaxLot(
            lot_id=lot_id,
            symbol=sym,
            qty=int(qty),
            unit_cost=float(price),
            total_cost=float(cost),
            bought_on=_today_et(),
            settles_on=_next_business_day(_today_et(), SETTLE_DAYS),
            used_unsettled=used_unsettled,
        )
        self._tax_lots.append(lot)
        if used_unsettled:
            logger.info(
                "compliance: %s lot %s bought with unsettled cash (cost=$%.2f, settled=$%.2f)",
                sym, lot_id, cost, settled_before,
            )

    def _close_lots_fifo(
        self,
        symbol: str,
        qty: int,
        proceeds_total: float,
    ) -> Tuple[float, List[Dict[str, Any]]]:
        """FIFO close; return (aggregate cost basis, per-slice closes for wash log)."""
        sym = symbol.upper()
        remaining = int(qty)
        cost_basis_total = 0.0
        closed_slices: List[Dict[str, Any]] = []
        new_lots: List[TaxLot] = []

        for lot in self._tax_lots:
            if lot.symbol != sym:
                new_lots.append(lot)
                continue
            if remaining <= 0:
                new_lots.append(lot)
                continue
            take = min(lot.qty, remaining)
            proceeds_slice = proceeds_total * (take / qty) if qty else 0.0
            cost_slice = take * lot.unit_cost
            cost_basis_total += cost_slice
            closed_slices.append(
                {
                    "lot_id": lot.lot_id,
                    "symbol": sym,
                    "qty": take,
                    "unit_cost": lot.unit_cost,
                    "cost_basis": cost_slice,
                    "proceeds": proceeds_slice,
                    "realized_pnl": proceeds_slice - cost_slice,
                    "bought_on": lot.bought_on.isoformat(),
                    "used_unsettled": lot.used_unsettled,
                    "settles_on": lot.settles_on.isoformat(),
                }
            )
            remaining -= take
            if lot.qty > take:
                new_lots.append(
                    TaxLot(
                        lot_id=lot.lot_id,
                        symbol=lot.symbol,
                        qty=lot.qty - take,
                        unit_cost=lot.unit_cost,
                        total_cost=lot.total_cost - cost_slice,
                        bought_on=lot.bought_on,
                        settles_on=lot.settles_on,
                        used_unsettled=lot.used_unsettled,
                    )
                )

        self._tax_lots = new_lots
        return cost_basis_total, closed_slices

    def record_sell(self, symbol: str, qty: int, price: float, cost_basis: float) -> None:
        """Sell: T+1 pending proceeds, FIFO tax lots, wash + GFV handling."""
        sym = symbol.upper()
        proceeds = qty * price
        sale_settle = _next_business_day(_today_et(), SETTLE_DAYS)
        self._pending_sales.append(PendingSaleSettlement(proceeds=proceeds, settles_on=sale_settle))

        basis_fifo, closed_slices = self._close_lots_fifo(sym, int(qty), proceeds)
        if abs(basis_fifo - cost_basis) > max(1.0, 0.01 * max(basis_fifo, cost_basis)) and basis_fifo > 0:
            logger.debug(
                "compliance: FIFO basis $%.2f vs engine cost_basis $%.2f for %s — using FIFO",
                basis_fifo, cost_basis, sym,
            )
        basis_use = basis_fifo if basis_fifo > 0 else float(cost_basis)

        disposal_date = _today_et()
        today = disposal_date
        agg_pnl = proceeds - basis_use

        self._realized.append(
            {
                "time": datetime.now(ET).isoformat(),
                "symbol": sym,
                "qty": int(qty),
                "proceeds": round(proceeds, 2),
                "cost_basis": round(basis_use, 2),
                "pnl": round(agg_pnl, 2),
                "hold_term": "short",
                "fifo_slices": len(closed_slices),
            }
        )
        self._persist_realized()

        for sl in closed_slices:
            pnl = float(sl["realized_pnl"])
            if pnl < 0:
                self._log_wash_sale_candidate(sl, disposal_date)
                until = disposal_date + timedelta(days=WASH_SALE_LOOKBACK_DAYS)
                prev = self._wash_sale_cooldown.get(sym)
                if prev is None or until > prev:
                    self._wash_sale_cooldown[sym] = until

            if sl["used_unsettled"] and date.fromisoformat(sl["settles_on"]) > today:
                self._gfv_events.append(today)
                logger.warning(
                    "compliance: GFV risk %s lot %s — sold before buy settlement (%s)",
                    sym, sl["lot_id"], sl["settles_on"],
                )

        if agg_pnl < 0:
            self._loss_streak += 1
        else:
            self._loss_streak = 0

    def _log_wash_sale_candidate(self, slice_: Dict[str, Any], disposal_date: date) -> None:
        """Append tax-lot wash-sale analytics (not tax advice)."""
        try:
            path = self._log_dir / f"wash-sales-{disposal_date.isoformat()}.jsonl"
            rec = {
                "event": "wash_sale_candidate",
                "lot_id": slice_["lot_id"],
                "symbol": slice_["symbol"],
                "qty": slice_["qty"],
                "cost_basis": round(float(slice_["cost_basis"]), 4),
                "proceeds": round(float(slice_["proceeds"]), 4),
                "realized_loss": round(abs(float(slice_["realized_pnl"])), 4),
                "disposal_date": disposal_date.isoformat(),
                "wash_window_end": (disposal_date + timedelta(days=WASH_SALE_LOOKBACK_DAYS)).isoformat(),
                "bought_on": slice_["bought_on"],
                "note": "Disallowed loss may apply if substantially identical shares repurchased within 30 days.",
            }
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("compliance: wash-sale log failed: %s", exc)

    def can_sell(self, symbol: str) -> bool:
        sym = symbol.upper()
        today = _today_et()
        for lot in self._tax_lots:
            if lot.symbol == sym and lot.used_unsettled and lot.settles_on > today:
                return False
        return True

    def can_enter(self, symbol: str) -> Optional[str]:
        sym = symbol.upper()
        until = self._wash_sale_cooldown.get(sym)
        if until and until > _today_et():
            return f"wash-sale cooldown until {until} (loss lot disposed — avoid re-entry or consult tax rules)"
        return None

    # ─── Cooldowns / circuit breaker ─────────────────────────────
    def register_loss_streak_cooldown(self, minutes: int = 15) -> None:
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
        pend = self._pending_sale_proceeds_unsettled()
        n_lots = len(self._tax_lots)
        return {
            "unsettled_sale_proceeds": round(pend, 2),
            "open_tax_lots": n_lots,
            # Back-compat for UI / older clients
            "unsettled_cash": round(pend, 2),
            "open_unsettled_lots": n_lots,
            "gfv_count_12mo": self.gfv_count_12mo,
            "gfv_level": self.gfv_warning_level(),
            "loss_streak": self._loss_streak,
            "cooling_down": self.is_cooling_down(),
            "cooldown_remaining_s": self.cooldown_remaining_s(),
            "wash_sale_cooldowns": {
                s: d.isoformat() for s, d in self._wash_sale_cooldown.items()
            },
            "t_plus_one_settlement_days": SETTLE_DAYS,
        }

    def _persist_realized(self) -> None:
        try:
            today = _today_et()
            path = self._log_dir / f"trades-{today.isoformat()}.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(self._realized[-1]) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.warning("compliance: failed to persist trade log: %s", exc)


compliance_service = ComplianceService()
