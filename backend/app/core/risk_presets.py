"""
Risk preset table for cash-account micro-scalping.

A single source of truth: both the trading engine and the REST API read
from ``RISK_PRESETS``. Market-regime score maps deterministically to a
preset via :func:`preset_for_score`, so UI, logs and execution all agree.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Literal

RiskLevel = Literal["conservative", "moderate", "aggressive"]


@dataclass(frozen=True)
class RiskPreset:
    level: RiskLevel
    # Sizing
    max_position_percent: float       # per-symbol % of equity
    max_concurrent_positions: int
    # Exits
    stop_loss_percent: float          # per-trade hard stop
    take_profit_percent: float        # per-trade profit target
    trailing_trigger_percent: float   # peak − now to trigger trail exit
    # Daily caps
    daily_loss_limit_percent: float
    daily_target_percent: float
    max_trades_per_day: int
    # Entry gating
    entry_score_threshold: int        # 0..100 signal score to enter
    spread_filter_percent: float      # skip symbols with wider spread
    universe_size: int
    # Macro guards
    vix_halt_level: float             # halt new entries if VIX above this
    blackout_window_minutes: int      # ± minutes around macro events
    # Extended hours never allowed for cash-scalp
    allow_extended_hours: bool = False

    def as_dict(self) -> Dict:
        return asdict(self)


RISK_PRESETS: Dict[RiskLevel, RiskPreset] = {
    "conservative": RiskPreset(
        level="conservative",
        max_position_percent=10.0,
        max_concurrent_positions=2,
        stop_loss_percent=0.20,
        take_profit_percent=0.50,
        trailing_trigger_percent=0.15,
        daily_loss_limit_percent=0.30,
        daily_target_percent=0.60,
        max_trades_per_day=20,
        entry_score_threshold=65,
        spread_filter_percent=0.03,
        universe_size=6,
        vix_halt_level=18.0,
        blackout_window_minutes=9999,  # whole day — skip macro event days
    ),
    "moderate": RiskPreset(
        level="moderate",
        max_position_percent=15.0,
        max_concurrent_positions=3,
        stop_loss_percent=0.30,
        take_profit_percent=0.80,
        trailing_trigger_percent=0.20,
        daily_loss_limit_percent=0.50,
        daily_target_percent=1.00,
        max_trades_per_day=40,
        entry_score_threshold=50,
        spread_filter_percent=0.05,
        universe_size=10,
        vix_halt_level=22.0,
        blackout_window_minutes=30,
    ),
    "aggressive": RiskPreset(
        level="aggressive",
        # Cash-safe aggressive:
        # - more opportunities (lower threshold / wider universe / more slots)
        # - smaller per-position size to avoid exhausting settled cash too fast
        max_position_percent=12.0,
        max_concurrent_positions=8,
        stop_loss_percent=0.35,
        take_profit_percent=0.70,
        trailing_trigger_percent=0.18,
        daily_loss_limit_percent=0.90,
        daily_target_percent=1.20,
        max_trades_per_day=160,
        entry_score_threshold=28,
        spread_filter_percent=0.12,
        universe_size=20,
        vix_halt_level=28.0,
        blackout_window_minutes=5,
    ),
}


def preset_for_level(level: str) -> RiskPreset:
    """Return the preset for a level name (case-insensitive, safe fallback)."""
    key = (level or "moderate").strip().lower()
    if key not in RISK_PRESETS:
        key = "moderate"
    return RISK_PRESETS[key]  # type: ignore[index]


def preset_for_score(score: float) -> RiskPreset:
    """
    Deterministic Market-Status → Risk preset mapping.

    - score >= 75   → aggressive
    - 55..74        → moderate
    - 35..54        → conservative
    - score < 35    → **halted** (still returns ``conservative`` so callers
      can read preset fields, but trading_engine must separately check
      :func:`is_halted_score`.)
    """
    s = float(score)
    if s >= 75:
        return RISK_PRESETS["aggressive"]
    if s >= 55:
        return RISK_PRESETS["moderate"]
    return RISK_PRESETS["conservative"]


def is_halted_score(score: float) -> bool:
    return float(score) < 35.0


def market_level_for_score(score: float) -> str:
    s = float(score)
    if s >= 80:
        return "EXCELLENT"
    if s >= 65:
        return "GOOD"
    if s >= 45:
        return "NORMAL"
    if s >= 30:
        return "BAD"
    return "DANGEROUS"
