"""
Risk preset table for cash-account scalping.

Three scales are supported:

- ``"3k"``  — **T+1 cash rotation** at small equity: low ``settled_cash_trade_cap``,
  fewer concurrent slots, modest daily trade counts; ``min_notional_*`` about USD 125–265
  so clips stay meaningful vs fees without exceeding typical max-position USD.
- ``"10k"`` — bridge scale: ``min_notional_*`` about USD 340–760 (roughly 2.5–3× 3k tier).
- ``"30k"`` — larger book: ``min_notional_*`` about USD 920–1.9k (roughly 6–7× 3k moderate slow),
  aligned with 6–8% of ~30k max-position clips and sell-side fee economics.

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
    # Daily caps (moderate-style headline defaults; tables override per level/scale)
    daily_loss_limit_percent: float = 1.00
    daily_target_percent: float = 1.50
    max_trades_per_day: int = 40
    # Entry gating
    entry_score_threshold: int = 50          # 0..100 signal score to enter
    spread_filter_percent: float = 0.05      # skip symbols with wider spread
    universe_size: int = 10
    # Macro guards
    vix_halt_level: float = 22.0             # halt new entries if VIX above this
    blackout_window_minutes: int = 30        # ± minutes around macro events
    # Sizing floors (USD notional) — slow = liquid large-caps; fast = tight-spread names
    # Tuned per ``scale`` (~$3k / $10k / $30k): higher notionals on larger books so
    # regulatory sell fees + spread don’t dominate; still ≤ typical max_position $ clip.
    min_notional_slow: float = 165.0
    min_notional_fast: float = 285.0
    # Max fraction of *settled* cash (post T+1 haircut in compliance) per entry
    settled_cash_trade_cap: float = 0.60
    # Preferred TIF for marketable limit entries: "ioc" | "fok" | "day"
    default_tif: str = "ioc"
    # Pre/post stock session (Alpaca: limit + DAY + extended_hours). Enable
    # globally with ALLOW_EXTENDED_HOURS=true — engine still requires extended
    # clock window (4–9:30a / 4–8p ET).
    allow_extended_hours: bool = False

    def as_dict(self) -> Dict:
        return asdict(self)


# ─── ~$3,000 nominal — smallest clips; floors ~5–10% of book so entries stay meaningful
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
        max_trades_per_day=18,
        entry_score_threshold=65,
        spread_filter_percent=0.03,
        universe_size=6,
        vix_halt_level=18.0,
        blackout_window_minutes=9999,
        min_notional_slow=125.0,
        min_notional_fast=215.0,
        settled_cash_trade_cap=0.36,
        default_tif="ioc",
    ),
    "moderate": RiskPreset(
        level="moderate",
        scale="3k",
        max_position_percent=15.0,
        max_concurrent_positions=2,
        stop_loss_percent=0.30,
        take_profit_percent=0.80,
        trailing_trigger_percent=0.20,
        daily_loss_limit_percent=1.00,
        daily_target_percent=1.50,
        max_trades_per_day=26,
        entry_score_threshold=50,
        spread_filter_percent=0.05,
        universe_size=8,
        vix_halt_level=22.0,
        blackout_window_minutes=30,
        min_notional_slow=155.0,
        min_notional_fast=265.0,
        settled_cash_trade_cap=0.40,
        default_tif="ioc",
    ),
    "aggressive": RiskPreset(
        level="aggressive",
        scale="3k",
        max_position_percent=12.0,
        max_concurrent_positions=5,
        stop_loss_percent=0.35,
        take_profit_percent=0.70,
        trailing_trigger_percent=0.18,
        daily_loss_limit_percent=0.90,
        daily_target_percent=1.20,
        max_trades_per_day=72,
        entry_score_threshold=28,
        spread_filter_percent=0.12,
        universe_size=16,
        vix_halt_level=28.0,
        blackout_window_minutes=5,
        min_notional_slow=145.0,
        min_notional_fast=255.0,
        settled_cash_trade_cap=0.46,
        default_tif="ioc",
    ),
}


# ─── ~$10,000 nominal — ~2.6× 3k floors; keeps typical clip under max_position % of $10k
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
        max_trades_per_day=38,
        entry_score_threshold=62,
        spread_filter_percent=0.03,
        universe_size=8,
        vix_halt_level=19.0,
        blackout_window_minutes=60,
        min_notional_slow=340.0,
        min_notional_fast=560.0,
        settled_cash_trade_cap=0.44,
        default_tif="ioc",
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
        daily_target_percent=1.50,           # $150
        max_trades_per_day=88,
        entry_score_threshold=48,
        spread_filter_percent=0.05,
        universe_size=14,
        vix_halt_level=23.0,
        blackout_window_minutes=25,
        min_notional_slow=400.0,
        min_notional_fast=660.0,
        settled_cash_trade_cap=0.52,
        default_tif="ioc",
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
        max_trades_per_day=240,
        entry_score_threshold=28,
        spread_filter_percent=0.10,
        universe_size=24,
        vix_halt_level=28.0,
        blackout_window_minutes=5,
        min_notional_slow=460.0,
        min_notional_fast=760.0,
        settled_cash_trade_cap=0.54,
        default_tif="ioc",
    ),
}


# ─── ~$30,000 nominal — ~10× 3k moderate slow anchor; sized vs 6–8% max clip ($1.8k–$2.4k)
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
        min_notional_slow=920.0,
        min_notional_fast=1480.0,
        settled_cash_trade_cap=0.44,
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
        daily_loss_limit_percent=1.0,       # $300
        daily_target_percent=1.50,          # $450
        max_trades_per_day=200,
        entry_score_threshold=45,
        spread_filter_percent=0.05,
        universe_size=18,
        vix_halt_level=24.0,
        blackout_window_minutes=20,
        min_notional_slow=1050.0,
        min_notional_fast=1720.0,
        settled_cash_trade_cap=0.52,
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
        min_notional_slow=1180.0,
        min_notional_fast=1920.0,
        settled_cash_trade_cap=0.56,
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
