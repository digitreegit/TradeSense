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
EQUITY_UNIVERSE: list[str] = [
    # Broad index ETFs
    "SPY", "QQQ", "IWM", "DIA",
    # Sector ETFs
    "XLK", "XLE", "XLF", "XLV", "XLI", "XLU", "XLP", "XLY",
    # Defensive / macro ETFs
    "GLD", "SLV", "TLT", "IEF",
    # Liquid megacaps
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO",
]

# Alpaca crypto symbols (24/7, no PDT, no settlement wait).
CRYPTO_UNIVERSE: list[str] = ["BTC/USD", "ETH/USD"]

# Symbols used only for regime detection.
REGIME_SYMBOL = "SPY"

# ---------------------------------------------------------------------------
# Strategy parameters (validated by scripts/run_backtest.py)
# ---------------------------------------------------------------------------
MOMENTUM_LOOKBACK = 63          # ~3 months of trading days
MOMENTUM_TOP_N = 3              # concurrent momentum holdings
MOMENTUM_REBALANCE_WEEKDAY = 0  # Monday
ATR_PERIOD = 14
MOMENTUM_STOP_ATR = 3.0         # wide trailing stop: ride trends, absorb noise

DIP_RSI_PERIOD = 2
DIP_RSI_ENTRY = 10.0            # RSI(2) < 10 on a long-term uptrend name
DIP_RSI_EXIT = 65.0
DIP_MAX_HOLD_DAYS = 10
DIP_STOP_ATR = 2.5
DIP_MAX_POSITIONS = 2

CRYPTO_FAST_EMA = 20
CRYPTO_SLOW_EMA = 50
CRYPTO_MAX_WEIGHT = 0.25        # crypto sleeve cap as fraction of equity

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

    # Alpaca
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_paper: bool = True

    # Engine
    trading_mode: str = "paper"          # paper | live
    initial_capital: float = 3000.0
    timezone: str = "America/New_York"

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

    @property
    def on_vercel(self) -> bool:
        import os
        return bool(os.environ.get("VERCEL"))

    @property
    def is_live(self) -> bool:
        return self.trading_mode.lower() == "live"


settings = Settings()
