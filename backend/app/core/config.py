"""TradeSense Backend Configuration"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load .env from the first existing path (many users keep .env at repo root).
_this_file = Path(__file__).resolve()
_backend_dir = _this_file.parent.parent.parent       # .../backend
_repo_root = _backend_dir.parent                     # parent of backend (project root)
_search_dirs = [
    _backend_dir,          # backend/.env
    _repo_root,            # TradeSense/.env (README often says cp .env.example here)
    Path.cwd(),            # wherever uvicorn was started from
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

    # Capital scale: "3k" | "10k" | "30k" | "auto"
    # "auto" picks based on ``initial_capital``:
    #   <$6,500 → 3k ; <$20,000 → 10k ; otherwise 30k
    capital_scale: str = os.getenv("CAPITAL_SCALE", "auto")

    # Streaming (Alpaca WebSocket)
    alpaca_data_feed: str = os.getenv("ALPACA_DATA_FEED", "iex")  # "iex" or "sip"
    streaming_enabled: bool = os.getenv("STREAMING_ENABLED", "true").lower() != "false"
    streaming_symbols: str = os.getenv("STREAMING_SYMBOLS", "")  # comma-separated override

    # Execution quality
    execution_log_enabled: bool = os.getenv("EXECUTION_LOG_ENABLED", "true").lower() != "false"
    default_order_tif: str = os.getenv("DEFAULT_ORDER_TIF", "day")  # "day" | "ioc"

    # AI
    ai_provider: str = os.getenv("AI_PROVIDER", "openai")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    google_api_key: str = os.getenv("GOOGLE_API_KEY", "")

    # Server
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))

    # Auth / multi-user (Supabase OAuth + encrypted Alpaca keys)
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "")
    supabase_jwt_secret: str = os.getenv("SUPABASE_JWT_SECRET", "")
    tradesense_secret_key: str = os.getenv("TRADESENSE_SECRET_KEY", "")

    # Notifications (Resend)
    resend_api_key: str = os.getenv("RESEND_API_KEY", "")
    resend_from_email: str = os.getenv("RESEND_FROM_EMAIL", "")
    receiver_email: str = (
        os.getenv("RESEND_DEFAULT_TO_EMAIL", "")
        or os.getenv("ALERT_RECIPIENTS", "")
        or os.getenv("RECEIVER_EMAIL", "")
    )

    # Telegram Bot API (shared bot; users set chat_id in Settings)
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_default_chat_id: str = os.getenv("TELEGRAM_DEFAULT_CHAT_ID", "")

    # Twilio WhatsApp (https://console.twilio.com — Messaging → Try WhatsApp)
    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_whatsapp_from: str = os.getenv("TWILIO_WHATSAPP_FROM", "")  # e.g. whatsapp:+14155238886

    class Config:
        env_file = _env_file_path or ".env"
        extra = "allow"


settings = Settings()


def initial_capital_for_scale(scale: str) -> float:
    """Notional starting capital for paper UI / virtual re-base (3k / 10k / 30k)."""
    s = (scale or "").strip().lower()
    if s == "10k":
        return 10_000.0
    if s == "30k":
        return 30_000.0
    return 3_000.0


def resolved_capital_scale() -> str:
    """Return '3k', '10k', or '30k'.

    Auto bands (when ``CAPITAL_SCALE=auto``):

    - < \\$6,500  → "3k"
    - < \\$20,000 → "10k"
    - otherwise  → "30k"
    """
    mode = (settings.capital_scale or "auto").strip().lower()
    if mode in ("3k", "10k", "30k"):
        return mode
    cap = float(settings.initial_capital or 0)
    if cap >= 20_000:
        return "30k"
    if cap >= 6_500:
        return "10k"
    return "3k"
