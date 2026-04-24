"""TradeSense Backend Configuration"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Primary search for .env in current and parent directory (backend/)
_this_file = Path(__file__).resolve()
_search_dirs = [
    _this_file.parent.parent.parent,          # backend/
    Path.cwd(),                               # CWD
]
_env_file_path = None
for _d in _search_dirs:
    try:
        _candidate = _d / ".env"
        if _candidate.is_file():
            _env_file_path = str(_candidate)
            load_dotenv(_env_file_path, override=True)
            break
    except Exception:
        continue



class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Alpaca
    alpaca_api_key: str = os.getenv("ALPACA_API_KEY", "")
    alpaca_secret_key: str = os.getenv("ALPACA_SECRET_KEY", "")
    alpaca_base_url: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    alpaca_data_url: str = os.getenv("ALPACA_DATA_URL", "https://data.alpaca.markets")

    # Trading
    trading_mode: str = os.getenv("TRADING_MODE", "paper")
    initial_capital: float = float(os.getenv("INITIAL_CAPITAL", "3000"))
    max_position_percent: float = float(os.getenv("MAX_POSITION_PERCENT", "15"))
    stop_loss_percent: float = float(os.getenv("STOP_LOSS_PERCENT", "0.3"))
    take_profit_percent: float = float(os.getenv("TAKE_PROFIT_PERCENT", "0.8"))
    max_daily_trades: int = int(os.getenv("MAX_DAILY_TRADES", "200"))
    risk_level: str = os.getenv("RISK_LEVEL", "moderate")

    # Cash account scalping
    daily_target_percent: float = float(os.getenv("DAILY_TARGET_PERCENT", "1.0"))
    daily_loss_limit_percent: float = float(os.getenv("DAILY_LOSS_LIMIT_PERCENT", "0.5"))
    account_type: str = os.getenv("ACCOUNT_TYPE", "cash")
    scan_interval_seconds: float = float(os.getenv("SCAN_INTERVAL_SECONDS", "1"))

    # AI
    ai_provider: str = os.getenv("AI_PROVIDER", "openai")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    google_api_key: str = os.getenv("GOOGLE_API_KEY", "")

    # Server
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))

    class Config:
        env_file = _env_file_path or ".env"
        extra = "allow"


settings = Settings()
