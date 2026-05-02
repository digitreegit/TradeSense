"""
Cash-account compliance tracking: GFV / free-riding + T+1 proceeds + tax lots.

- **T+1 settlement** (SEC 34-96930, 2024-05-28): sell proceeds are modelled as
  unavailable until the settlement date; ``settled_cash()`` subtracts only
  *still-unsettled* pending sale amounts (not a monotonic lump sum).

- **Tax lots (FIFO)**: each buy opens a lot with a stable ``lot_id``. Sells
  close lots first-in-first-out so realized P/L and wash-sale candidates are
  logged per closed lot.

- **Hold term split**: each FIFO slice gets a per-slice ``hold_term`` of
  ``"long"`` (held > 365 days) or ``"short"`` (≤ 365 days). The aggregate
  realized row reflects ``"long"`` / ``"short"`` / ``"mixed"`` so downstream
  tax tooling can split LTCG vs STCG.

- **Wash-sale basis carry**: when a lot is sold at a loss, the disallowed loss
  is parked on a per-symbol pending list for 30 days. Subsequent ``record_buy``
  for the same symbol within that window pulls the deferred loss into the new
  lot's cost basis (substantially-identical heuristic; same-symbol only).

State is persisted per ``log_dir`` to ``compliance_state.json`` (atomic
rename) so engine restarts don't drop open lots / GFV history / wash carry.
JSONL under ``TRADESENSE_LOG_DIR`` continues to be the durable audit trail
for realized trades and wash-sale analytics.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytz

ET = pytz.timezone("America/New_York")
logger = logging.getLogger(__name__)

# Settlement for US equities is T+1 as of 2024-05-28 (SEC Release 34-96930).
SETTLE_DAYS = 1
WASH_SALE_LOOKBACK_DAYS = 30
LONG_TERM_HOLD_DAYS = 365


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


def _hold_term_for(bought_on: date, disposal_date: date) -> str:
    """IRS uses > 1 year for long-term; same-day or shorter is short-term."""
    days_held = (disposal_date - bought_on).days
    return "long" if days_held > LONG_TERM_HOLD_DAYS else "short"


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
    # Wash-sale basis adjustment: USD added to ``unit_cost`` * ``qty`` when this
    # lot inherited a deferred loss from a recent sale of the same symbol.
    wash_basis_adjustment: float = 0.0


@dataclass
class PendingSaleSettlement:
    """Sell proceeds not yet settled (T+1)."""

    proceeds: float
    settles_on: date


@dataclass
class WashLossCarry:
    """Disallowed loss parked for the 30-day wash window after a loss sale."""

    symbol: str
    disallowed_loss: float
    disposal_date: date
    expires_on: date
    consumed: float = 0.0  # USD already absorbed into a replacement lot


class ComplianceService:
    """
    GFV tracker + T+1 pending proceeds + FIFO tax lots + wash-sale logging.

    ``record_buy`` opens a tax lot (and absorbs any pending wash-sale loss into
    the new lot's cost basis). ``record_sell`` closes lots FIFO, books pending
    settlement for proceeds, logs wash-sale candidates per closed lot on
    losses, parks the disallowed loss for the 30-day window, and enforces a
    conservative re-entry cooldown per symbol.
    """

    STATE_VERSION = 2

    def __init__(self, log_dir: Optional[Path] = None):
        self._tax_lots: List[TaxLot] = []
        self._pending_sales: List[PendingSaleSettlement] = []
        self._gfv_events: List[date] = []
        self._wash_sale_cooldown: Dict[str, date] = {}
        self._wash_loss_carries: List[WashLossCarry] = []
        self._realized: List[dict] = []
        self._loss_streak: int = 0
        self._cooldown_until: Optional[datetime] = None
        self._state_lock = threading.Lock()

        self._log_dir = log_dir or Path(os.getenv("TRADESENSE_LOG_DIR", "./trade_logs"))
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._state_path = self._log_dir / "compliance_state.json"
        self._load_state()

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
        before_pend = len(self._pending_sales)
        self._pending_sales = [p for p in self._pending_sales if p.settles_on > today]
        for lot in self._tax_lots:
            if lot.settles_on <= today:
                lot.used_unsettled = False
        before_carry = len(self._wash_loss_carries)
        self._wash_loss_carries = [
            c for c in self._wash_loss_carries if c.expires_on >= today
        ]
        if (
            len(self._pending_sales) != before_pend
            or len(self._wash_loss_carries) != before_carry
        ):
            self._save_state()

    # ─── Buy / sell hooks ───────────────────────────────────────
    def _consume_wash_carry(self, symbol: str, qty: int) -> float:
        """Pull disallowed loss for the 30-day window into the new lot's basis.

        Returns the total USD added to cost basis (>= 0). Carries are consumed
        FIFO across the disposal_date so older deferred losses are reabsorbed
        first; partial consumption is supported when an old carry's loss
        exceeds what the new lot can absorb.
        """
        if qty <= 0:
            return 0.0
        sym = symbol.upper()
        today = _today_et()
        added = 0.0
        # FIFO over disposal_date
        carries = sorted(
            (c for c in self._wash_loss_carries if c.symbol == sym and c.expires_on >= today),
            key=lambda c: c.disposal_date,
        )
        for c in carries:
            remaining = c.disallowed_loss - c.consumed
            if remaining <= 0:
                continue
            c.consumed += remaining
            added += remaining
        return float(added)

    def record_buy(self, symbol: str, qty: int, price: float, settled_before: float) -> None:
        sym = symbol.upper()
        cost = qty * price
        used_unsettled = cost > settled_before + 1e-6
        lot_id = uuid.uuid4().hex[:12]

        wash_add = self._consume_wash_carry(sym, int(qty))
        adjusted_total = float(cost) + wash_add
        adjusted_unit = adjusted_total / int(qty) if qty else float(price)

        lot = TaxLot(
            lot_id=lot_id,
            symbol=sym,
            qty=int(qty),
            unit_cost=float(adjusted_unit),
            total_cost=float(adjusted_total),
            bought_on=_today_et(),
            settles_on=_next_business_day(_today_et(), SETTLE_DAYS),
            used_unsettled=used_unsettled,
            wash_basis_adjustment=float(wash_add),
        )
        self._tax_lots.append(lot)
        if used_unsettled:
            logger.info(
                "compliance: %s lot %s bought with unsettled cash (cost=$%.2f, settled=$%.2f)",
                sym, lot_id, cost, settled_before,
            )
        if wash_add > 0:
            logger.info(
                "compliance: wash-sale basis carry $%.2f added to %s lot %s (raw cost=$%.2f → adj=$%.2f)",
                wash_add, sym, lot_id, cost, adjusted_total,
            )
        self._save_state()

    def _close_lots_fifo(
        self,
        symbol: str,
        qty: int,
        proceeds_total: float,
        disposal_date: date,
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
                    "hold_term": _hold_term_for(lot.bought_on, disposal_date),
                    "wash_basis_adjustment": float(lot.wash_basis_adjustment),
                }
            )
            remaining -= take
            if lot.qty > take:
                # Pro-rate the existing wash-sale basis adjustment so the
                # remaining slice keeps its share of the deferred-loss markup.
                kept = lot.qty - take
                wash_kept = (
                    lot.wash_basis_adjustment * (kept / lot.qty)
                    if lot.qty
                    else 0.0
                )
                new_lots.append(
                    TaxLot(
                        lot_id=lot.lot_id,
                        symbol=lot.symbol,
                        qty=kept,
                        unit_cost=lot.unit_cost,
                        total_cost=lot.total_cost - cost_slice,
                        bought_on=lot.bought_on,
                        settles_on=lot.settles_on,
                        used_unsettled=lot.used_unsettled,
                        wash_basis_adjustment=float(wash_kept),
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

        disposal_date = _today_et()
        basis_fifo, closed_slices = self._close_lots_fifo(
            sym, int(qty), proceeds, disposal_date
        )
        if abs(basis_fifo - cost_basis) > max(1.0, 0.01 * max(basis_fifo, cost_basis)) and basis_fifo > 0:
            logger.debug(
                "compliance: FIFO basis $%.2f vs engine cost_basis $%.2f for %s — using FIFO",
                basis_fifo, cost_basis, sym,
            )
        basis_use = basis_fifo if basis_fifo > 0 else float(cost_basis)

        today = disposal_date
        agg_pnl = proceeds - basis_use

        # Aggregate hold_term: long if all slices long, short if all short, else mixed.
        slice_terms = {sl.get("hold_term", "short") for sl in closed_slices}
        if not slice_terms:
            agg_term = "short"
        elif slice_terms == {"long"}:
            agg_term = "long"
        elif slice_terms == {"short"}:
            agg_term = "short"
        else:
            agg_term = "mixed"

        self._realized.append(
            {
                "time": datetime.now(ET).isoformat(),
                "symbol": sym,
                "qty": int(qty),
                "proceeds": round(proceeds, 2),
                "cost_basis": round(basis_use, 2),
                "pnl": round(agg_pnl, 2),
                "hold_term": agg_term,
                "fifo_slices": len(closed_slices),
                "slice_terms": [sl.get("hold_term") for sl in closed_slices],
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
                # Park the disallowed loss for re-absorption into a replacement lot.
                self._wash_loss_carries.append(
                    WashLossCarry(
                        symbol=sym,
                        disallowed_loss=abs(pnl),
                        disposal_date=disposal_date,
                        expires_on=until,
                    )
                )

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
        self._save_state()

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
                "hold_term": slice_.get("hold_term", "short"),
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

    def is_gfv_restricted(self) -> bool:
        """``RESTRICTED`` (≥3 GFV events in 12 months) → freeze new entries."""
        return self.gfv_warning_level() == "RESTRICTED"

    def status(self) -> dict:
        pend = self._pending_sale_proceeds_unsettled()
        n_lots = len(self._tax_lots)
        carries_active = sum(
            1 for c in self._wash_loss_carries if c.expires_on >= _today_et()
        )
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
            "wash_loss_carries_active": carries_active,
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

    # ─── Persistent state (atomic rename) ───────────────────────
    def _serializable_state(self) -> dict:
        def _d(x: date) -> str:
            return x.isoformat()

        return {
            "version": self.STATE_VERSION,
            "saved_at": datetime.now(ET).isoformat(),
            "tax_lots": [
                {
                    **asdict(lot),
                    "bought_on": _d(lot.bought_on),
                    "settles_on": _d(lot.settles_on),
                }
                for lot in self._tax_lots
            ],
            "pending_sales": [
                {"proceeds": p.proceeds, "settles_on": _d(p.settles_on)}
                for p in self._pending_sales
            ],
            "gfv_events": [_d(d) for d in self._gfv_events],
            "wash_sale_cooldown": {
                s: _d(d) for s, d in self._wash_sale_cooldown.items()
            },
            "wash_loss_carries": [
                {
                    "symbol": c.symbol,
                    "disallowed_loss": c.disallowed_loss,
                    "disposal_date": _d(c.disposal_date),
                    "expires_on": _d(c.expires_on),
                    "consumed": c.consumed,
                }
                for c in self._wash_loss_carries
            ],
            "loss_streak": int(self._loss_streak),
            "cooldown_until": (
                self._cooldown_until.isoformat() if self._cooldown_until else None
            ),
        }

    def _save_state(self) -> None:
        """Atomically write state to disk via tempfile + rename."""
        with self._state_lock:
            try:
                payload = self._serializable_state()
                tmp = tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    dir=str(self._log_dir),
                    prefix=".compliance_state-",
                    suffix=".tmp",
                    delete=False,
                )
                try:
                    json.dump(payload, tmp, default=str)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                finally:
                    tmp.close()
                os.replace(tmp.name, self._state_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("compliance: failed to save state: %s", exc)

    def _load_state(self) -> None:
        """Restore from prior session if present; missing/corrupt file = clean slate."""
        if not self._state_path.exists():
            return
        try:
            with self._state_path.open(encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            logger.warning("compliance: state file unreadable, starting clean: %s", exc)
            return

        if not isinstance(payload, dict):
            return

        def _date(s: str) -> Optional[date]:
            if not s:
                return None
            try:
                return date.fromisoformat(s[:10])
            except ValueError:
                return None

        try:
            for lot_raw in payload.get("tax_lots") or []:
                bo = _date(str(lot_raw.get("bought_on") or ""))
                so = _date(str(lot_raw.get("settles_on") or ""))
                if bo is None or so is None:
                    continue
                self._tax_lots.append(
                    TaxLot(
                        lot_id=str(lot_raw.get("lot_id") or uuid.uuid4().hex[:12]),
                        symbol=str(lot_raw.get("symbol") or "").upper(),
                        qty=int(lot_raw.get("qty") or 0),
                        unit_cost=float(lot_raw.get("unit_cost") or 0.0),
                        total_cost=float(lot_raw.get("total_cost") or 0.0),
                        bought_on=bo,
                        settles_on=so,
                        used_unsettled=bool(lot_raw.get("used_unsettled") or False),
                        wash_basis_adjustment=float(
                            lot_raw.get("wash_basis_adjustment") or 0.0
                        ),
                    )
                )
            for p_raw in payload.get("pending_sales") or []:
                so = _date(str(p_raw.get("settles_on") or ""))
                if so is None:
                    continue
                self._pending_sales.append(
                    PendingSaleSettlement(
                        proceeds=float(p_raw.get("proceeds") or 0.0),
                        settles_on=so,
                    )
                )
            for d_raw in payload.get("gfv_events") or []:
                d = _date(str(d_raw))
                if d is not None:
                    self._gfv_events.append(d)
            for sym_raw, d_raw in (payload.get("wash_sale_cooldown") or {}).items():
                d = _date(str(d_raw))
                if d is not None and sym_raw:
                    self._wash_sale_cooldown[str(sym_raw).upper()] = d
            for c_raw in payload.get("wash_loss_carries") or []:
                dd = _date(str(c_raw.get("disposal_date") or ""))
                eo = _date(str(c_raw.get("expires_on") or ""))
                if dd is None or eo is None:
                    continue
                self._wash_loss_carries.append(
                    WashLossCarry(
                        symbol=str(c_raw.get("symbol") or "").upper(),
                        disallowed_loss=float(c_raw.get("disallowed_loss") or 0.0),
                        disposal_date=dd,
                        expires_on=eo,
                        consumed=float(c_raw.get("consumed") or 0.0),
                    )
                )
            self._loss_streak = int(payload.get("loss_streak") or 0)
            cu_raw = payload.get("cooldown_until")
            if cu_raw:
                try:
                    self._cooldown_until = datetime.fromisoformat(cu_raw)
                except ValueError:
                    self._cooldown_until = None
            logger.info(
                "compliance: restored state from %s — lots=%d gfv=%d wash_carries=%d",
                self._state_path,
                len(self._tax_lots),
                len(self._gfv_events),
                len(self._wash_loss_carries),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("compliance: state restore partial failure: %s", exc)


compliance_service = ComplianceService()
