"""Position sizing and the portfolio drawdown brake.

Sizing takes risk seriously but does not strangle the system:
- each position risks ~2% of equity to its stop (stop distance = k * ATR)
- single-name cap 40%
- drawdown brake with hysteresis instead of v1's ~0.3% daily kill-switch
"""
from __future__ import annotations

from dataclasses import dataclass

from . import config


def position_dollars(
    equity: float,
    slot_weight: float,
    price: float,
    atr_value: float,
    stop_mult: float,
    exposure: float = 1.0,
    dd_scale: float = 1.0,
) -> float:
    """Dollar allocation for a new position.

    Takes the minimum of:
    - the sleeve slot allocation (weight * exposure * equity)
    - the stop-based risk budget (risk% * equity / stop distance)
    - the single-name cap
    then applies the drawdown scale.
    """
    if price <= 0 or atr_value <= 0:
        return 0.0
    slot = equity * slot_weight * exposure
    stop_frac = (stop_mult * atr_value) / price
    risk_budget = equity * config.RISK_PER_TRADE / max(stop_frac, 1e-6)
    cap = equity * config.MAX_POSITION_WEIGHT
    dollars = min(slot, risk_budget, cap) * dd_scale
    return dollars if dollars >= config.MIN_ORDER_NOTIONAL else 0.0


@dataclass
class DrawdownBrake:
    """Hysteresis brake on portfolio drawdown.

    normal  -> soft (dd > 15%): halve new position sizes
    soft    -> hard (dd > 25%): liquidate, stop trading
    hard    -> normal only after dd recovers below 20%
    """

    peak_equity: float = 0.0
    halted: bool = False

    def update(self, equity: float) -> None:
        self.peak_equity = max(self.peak_equity, equity)
        dd = self.drawdown(equity)
        if self.halted:
            if dd < config.DD_RESUME:
                self.halted = False
        elif dd > config.DD_HARD_BRAKE:
            self.halted = True

    def drawdown(self, equity: float) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return 1.0 - equity / self.peak_equity

    def scale(self, equity: float) -> float:
        """Size multiplier for NEW entries."""
        if self.halted:
            return 0.0
        if self.drawdown(equity) > config.DD_SOFT_BRAKE:
            return 0.5
        return 1.0
