"""
Risk preset table for cash-account scalping.

Three scales are supported:

- ``"3k"``  — legacy $3,000 cash-scalp (tight settled-cash turnover).
- ``"10k"`` — $10,000 bridge: enough settled cash for real rotation but
  still below the marginable PDT threshold, so cash-only scalping stays
  simple. Tuned to split the difference between 3k and 30k.
- ``"30k"`` — $30,000 paper HFT test (Algo Trader Plus + SIP + us-east-1
  cloud latency budget). More slots, tighter stops, larger daily trade
  cap, and looser per-trade notional minimums so fills are meaningful.

All three assume a **cash account** (no margin, no shorting). The PDT
(Pattern Day Trader) rule only applies to *margin* accounts — a cash
account can day-trade freely as long as it respects T+1 settlement and
the GFV/free-riding rules, which ``ComplianceService`` enforces. So the
$25k PDT threshold does **not** gate the 10k preset.

Both UI and trading engine read from ``RISK_PRESETS_FOR(scale)``, so the
active scale is a single source of truth. Market-regime score maps
deterministically to a preset via :func:`preset_for_score`.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Literal

RiskLevel = Literal["conservative", "moderate", "aggressive"]
CapitalScale = Literal["3k", "10k", "30k"]


@dataclass(frozen=True)
class RiskPreset:
    level: RiskLevel
    scale: CapitalScale = "3k"
    # Sizing
    max_position_percent: float = 15.0       # per-symbol % of equity
    max_concurrent_positions: int = 3
    # Exits
    stop_loss_percent: float = 0.30          # per-trade hard stop
    take_profit_percent: float = 0.80        # per-trade profit target
    trailing_trigger_percent: float = 0.20   # peak − now to trigger trail exit
    # Daily caps
    daily_loss_limit_percent: float = 0.50
    daily_target_percent: float = 1.00
    max_trades_per_day: int = 40
    # Entry gating
    entry_score_threshold: int = 50          # 0..100 signal score to enter
    spread_filter_percent: float = 0.05      # skip symbols with wider spread
    universe_size: int = 10
    # Macro guards
    vix_halt_level: float = 22.0             # halt new entries if VIX above this
    blackout_window_minutes: int = 30        # ± minutes around macro events
    # Sizing floors (USD notional) — symbol-type aware; engine may multiply
    min_notional_slow: float = 180.0
    min_notional_fast: float = 300.0
    # Cash-utilization cap (fraction of settled cash allowed per trade)
    settled_cash_trade_cap: float = 0.60
    # Preferred TIF for limit entries: "day" | "ioc"
    default_tif: str = "day"
    # Extended hours never allowed for cash-scalp
    allow_extended_hours: bool = False

    def as_dict(self) -> Dict:
        return asdict(self)


# ─── $3,000 cash-scalp (legacy) ────────────────────────────────────────
_PRESETS_3K: Dict[RiskLevel, RiskPreset] = {
    "conservative": RiskPreset(
        level="conservative",
        scale="3k",
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
        blackout_window_minutes=9999,
        min_notional_slow=180.0,
        min_notional_fast=300.0,
        settled_cash_trade_cap=0.50,
        default_tif="day",
    ),
    "moderate": RiskPreset(
        level="moderate",
        scale="3k",
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
        min_notional_slow=180.0,
        min_notional_fast=300.0,
        settled_cash_trade_cap=0.60,
        default_tif="day",
    ),
    "aggressive": RiskPreset(
        level="aggressive",
        scale="3k",
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
        min_notional_slow=180.0,
        min_notional_fast=300.0,
        settled_cash_trade_cap=0.60,
        default_tif="day",
    ),
}


# ─── $10,000 bridge scale ──────────────────────────────────────────────
# Sits between 3k and 30k. Design rationale:
# - Still cash-only (no margin, no shorting) → PDT rule doesn't apply.
# - Enough settled cash that 4–8 concurrent rotations are realistic
#   without starving GFV room, so we bump slot count and trade cap
#   materially vs 3k.
# - Per-trade min notional is raised modestly so SEC fee + TAF don't
#   disproportionately eat profits at small-share scalps.
# - Default TIF stays DAY on conservative/moderate (simpler, lets
#   partial fills still work), switches to IOC on aggressive where
#   rapid turnover matters more than hit-rate.
# - Settled-cash cap between the two neighbours (~0.50).
_PRESETS_10K: Dict[RiskLevel, RiskPreset] = {
    "conservative": RiskPreset(
        level="conservative",
        scale="10k",
        max_position_percent=8.0,
        max_concurrent_positions=4,
        stop_loss_percent=0.18,
        take_profit_percent=0.45,
        trailing_trigger_percent=0.14,
        daily_loss_limit_percent=0.60,       # $60
        daily_target_percent=0.70,           # $70
        max_trades_per_day=40,
        entry_score_threshold=62,
        spread_filter_percent=0.03,
        universe_size=8,
        vix_halt_level=19.0,
        blackout_window_minutes=60,
        min_notional_slow=350.0,
        min_notional_fast=600.0,
        settled_cash_trade_cap=0.45,
        default_tif="day",
    ),
    "moderate": RiskPreset(
        level="moderate",
        scale="10k",
        max_position_percent=10.0,
        max_concurrent_positions=6,
        stop_loss_percent=0.25,
        take_profit_percent=0.60,
        trailing_trigger_percent=0.18,
        daily_loss_limit_percent=1.00,       # $100
        daily_target_percent=1.00,           # $100
        max_trades_per_day=100,
        entry_score_threshold=48,
        spread_filter_percent=0.05,
        universe_size=14,
        vix_halt_level=23.0,
        blackout_window_minutes=25,
        min_notional_slow=450.0,
        min_notional_fast=800.0,
        settled_cash_trade_cap=0.50,
        default_tif="day",
    ),
    "aggressive": RiskPreset(
        level="aggressive",
        scale="10k",
        max_position_percent=9.0,
        max_concurrent_positions=10,
        stop_loss_percent=0.28,
        take_profit_percent=0.55,
        trailing_trigger_percent=0.16,
        daily_loss_limit_percent=1.50,       # $150
        daily_target_percent=1.30,           # $130
        max_trades_per_day=280,
        entry_score_threshold=28,
        spread_filter_percent=0.10,
        universe_size=24,
        vix_halt_level=28.0,
        blackout_window_minutes=5,
        min_notional_slow=500.0,
        min_notional_fast=1000.0,
        settled_cash_trade_cap=0.55,
        default_tif="ioc",
    ),
}


# ─── $30,000 HFT paper test ────────────────────────────────────────────
_PRESETS_30K: Dict[RiskLevel, RiskPreset] = {
    "conservative": RiskPreset(
        level="conservative",
        scale="30k",
        max_position_percent=6.0,
        max_concurrent_positions=6,
        stop_loss_percent=0.15,
        take_profit_percent=0.35,
        trailing_trigger_percent=0.12,
        daily_loss_limit_percent=1.0,       # $300
        daily_target_percent=0.60,          # $180
        max_trades_per_day=80,
        entry_score_threshold=60,
        spread_filter_percent=0.03,
        universe_size=12,
        vix_halt_level=20.0,
        blackout_window_minutes=45,
        min_notional_slow=600.0,
        min_notional_fast=1000.0,
        settled_cash_trade_cap=0.35,
        default_tif="ioc",
    ),
    "moderate": RiskPreset(
        level="moderate",
        scale="30k",
        max_position_percent=8.0,
        max_concurrent_positions=10,
        stop_loss_percent=0.20,
        take_profit_percent=0.45,
        trailing_trigger_percent=0.15,
        daily_loss_limit_percent=1.5,       # $450
        daily_target_percent=1.00,          # $300
        max_trades_per_day=200,
        entry_score_threshold=45,
        spread_filter_percent=0.05,
        universe_size=18,
        vix_halt_level=24.0,
        blackout_window_minutes=20,
        min_notional_slow=800.0,
        min_notional_fast=1500.0,
        settled_cash_trade_cap=0.40,
        default_tif="ioc",
    ),
    "aggressive": RiskPreset(
        level="aggressive",
        scale="30k",
        max_position_percent=7.0,
        max_concurrent_positions=14,
        stop_loss_percent=0.22,
        take_profit_percent=0.40,
        trailing_trigger_percent=0.14,
        daily_loss_limit_percent=2.0,       # $600 — global killswitch
        daily_target_percent=1.50,          # $450
        max_trades_per_day=500,
        entry_score_threshold=26,
        spread_filter_percent=0.08,
        universe_size=30,
        vix_halt_level=28.0,
        blackout_window_minutes=5,
        min_notional_slow=900.0,
        min_notional_fast=1800.0,
        settled_cash_trade_cap=0.45,
        default_tif="ioc",
    ),
}


# Back-compat: code that still imports ``RISK_PRESETS`` gets the 3k scale.
RISK_PRESETS: Dict[RiskLevel, RiskPreset] = _PRESETS_3K


def RISK_PRESETS_FOR(scale: str) -> Dict[RiskLevel, RiskPreset]:
    s = (scale or "3k").strip().lower()
    if s == "30k":
        return _PRESETS_30K
    if s == "10k":
        return _PRESETS_10K
    return _PRESETS_3K


def _active_scale() -> str:
    try:
        from app.core.config import resolved_capital_scale
        return resolved_capital_scale()
    except Exception:
        return "3k"


def preset_for_level(level: str, scale: str = None) -> RiskPreset:
    """Return the preset for a level name (case-insensitive, safe fallback)."""
    key = (level or "moderate").strip().lower()
    table = RISK_PRESETS_FOR(scale or _active_scale())
    if key not in table:
        key = "moderate"
    return table[key]  # type: ignore[index]


def preset_for_score(score: float, scale: str = None) -> RiskPreset:
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
    table = RISK_PRESETS_FOR(scale or _active_scale())
    if s >= 75:
        return table["aggressive"]
    if s >= 55:
        return table["moderate"]
    return table["conservative"]


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
