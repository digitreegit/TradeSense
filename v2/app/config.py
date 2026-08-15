"""TradeSense v2 configuration.

Philosophy: buy low, sell high, on a daily-bar timescale.
No scalping, no 1-second loops, no paid data feeds required.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

# ---------------------------------------------------------------------------
# Trading universe
# ---------------------------------------------------------------------------
# Mixed universe so momentum can rotate into defensive assets (gold, bonds)
# in bad tape instead of being forced to sit 100% cash.
EQUITY_ETFS: list[str] = [
    # Broad index ETFs
    "SPY", "QQQ", "IWM", "DIA",
    # Sector ETFs
    "XLK", "XLE", "XLF", "XLV", "XLI", "XLU", "XLP", "XLY",
    # Defensive / macro ETFs
    "GLD", "SLV", "TLT", "IEF",
]
# Liquid megacaps — carry earnings-gap risk that ETFs don't.
MEGACAPS: list[str] = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO",
]
# High-volatility names from the 2026-08 research (scripts/compare_universe.py).
# Adding them to the momentum/dip universe beat the megacap-only baseline in
# walk-forward starts 2018/2020/2022/2023 (e.g. 2018: 20.2% -> 29.1% CAGR)
# with max drawdown staying inside the brake limits. A RuleFive-style ±1%
# grid on the same names LOST money in every tested period (scripts/grid_sim.py)
# — ride these names with trend + stops, don't fade them.
VOLATILE_STOCKS: list[str] = [
    "AMD", "PLTR", "COIN", "MSTR", "SMCI",
]
SINGLE_STOCKS: list[str] = MEGACAPS + VOLATILE_STOCKS
EQUITY_UNIVERSE: list[str] = EQUITY_ETFS + SINGLE_STOCKS

# Single stocks retain an earnings-gap discount versus ETFs, but 0.65 keeps
# enough participation for a growth-led bull market. Walk-forward starts
# 2018/2020/2022/2024 improved CAGR/Sharpe versus the former 0.50 setting.
SINGLE_NAME_SCALE = 0.65

# Alpaca crypto — NOT available in NJ and many US states. See:
# https://alpaca.markets/support/alpaca-cryptocurrency
CRYPTO_UNIVERSE: list[str] = ["BTC/USD", "ETH/USD"]

# Third sleeve when crypto is disabled: macro/defensive trend (GLD/TLT/IEF).
DEFENSIVE_UNIVERSE: list[str] = ["GLD", "TLT", "IEF"]
# Keep defensive assets out of the momentum ranking. Previously GLD/TLT/IEF
# could be selected by both sleeves on the same decision and the live executor
# could submit duplicate buys for one symbol.
MOMENTUM_UNIVERSE: list[str] = [
    s for s in EQUITY_UNIVERSE if s not in DEFENSIVE_UNIVERSE
]

# Symbols used only for regime detection.
REGIME_SYMBOL = "SPY"

# ---------------------------------------------------------------------------
# Strategy parameters (validated by scripts/run_backtest.py)
# ---------------------------------------------------------------------------
MOMENTUM_LOOKBACK = 63          # ~3 months of trading days
MOMENTUM_TOP_N = 3              # concurrent momentum holdings
MOMENTUM_REBALANCE_WEEKDAY = 0  # Monday
# Rank by absolute return. The former return/volatility score systematically
# preferred slow, low-beta names (DIA/XLF/XLV) during strong growth markets.
# Cached walk-forward tests (2018/2020/2022/2024 starts) showed higher CAGR
# and Sharpe for raw return after costs, without a worse recent max drawdown.
MOMENTUM_VOL_PENALTY = 0.0      # 0=raw return; 1=return / annualized vol
ATR_PERIOD = 14
MOMENTUM_STOP_ATR = 3.0         # wide trailing stop: ride trends, absorb noise

DIP_RSI_PERIOD = 2
DIP_RSI_ENTRY = 10.0            # RSI(2) < 10 on a long-term uptrend name
DIP_RSI_EXIT = 65.0
DIP_PROFIT_TARGET = 0.04        # lock a 4% rebound; momentum keeps running
DIP_ENTRY_MIN_VOLUME_RATIO = 1.0  # ignore low-participation dips
DIP_MAX_HOLD_DAYS = 10
DIP_STOP_ATR = 2.5
DIP_MAX_POSITIONS = 2

# A very long upper wick on >=2x normal volume marks a failed rally. This is
# deliberately rare and applies only to momentum positions.
DISTRIBUTION_EXIT_ENABLED = True
DISTRIBUTION_MIN_VOLUME_RATIO = 2.0
DISTRIBUTION_MIN_UPPER_WICK = 0.60

CRYPTO_FAST_EMA = 20
CRYPTO_SLOW_EMA = 50
CRYPTO_MAX_WEIGHT = 0.25        # crypto sleeve cap as fraction of equity
DEFENSIVE_MAX_WEIGHT = 0.25     # defensive sleeve cap (replaces crypto when disabled)

# ---------------------------------------------------------------------------
# Regime -> gross exposure
# ---------------------------------------------------------------------------
EXPOSURE_BY_REGIME = {
    "BULL": 1.00,
    "CHOP": 0.60,
    "BEAR": 0.25,
}

# ---------------------------------------------------------------------------
# Risk (deliberately NOT the v1 straitjacket)
# ---------------------------------------------------------------------------
RISK_PER_TRADE = 0.02           # 2% of equity at risk per position (stop-based)
MAX_POSITION_WEIGHT = 0.40      # single-name cap
DD_SOFT_BRAKE = 0.15            # drawdown > 15%: halve position sizes
DD_HARD_BRAKE = 0.25            # drawdown > 25%: go flat
DD_RESUME = 0.20                # resume trading once drawdown recovers < 20%
MIN_ORDER_NOTIONAL = 10.0       # Alpaca fractional minimum is $1; keep sane floor


class Settings(BaseSettings):
    """Runtime settings from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ROOT_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Alpaca — live trading only (paper mode removed)
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""

    # Engine
    trading_mode: str = "live"           # live only; kept for logging/compat
    initial_capital: float = 3000.0
    timezone: str = "America/New_York"
    # NJ and many US states cannot trade crypto on Alpaca — default off.
    crypto_enabled: bool = False

    # Optional LLM news overlay
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Storage: Postgres (Supabase pooled URL) on Vercel, SQLite locally
    database_url: str = ""
    db_path: str = str(DATA_DIR / "tradesense.db")

    # Cron endpoint protection (Vercel sends Authorization: Bearer $CRON_SECRET)
    cron_secret: str = ""

    # Dashboard / settings API protection. Falls back to CRON_SECRET when
    # unset. If neither is set, admin routes are open only outside Vercel.
    admin_token: str = ""

    @property
    def on_vercel(self) -> bool:
        import os
        return bool(os.environ.get("VERCEL"))

    @property
    def is_live(self) -> bool:
        return True


settings = Settings()
