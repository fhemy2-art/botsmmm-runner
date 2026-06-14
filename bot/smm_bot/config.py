"""
Bot configuration — loaded from environment variables or .env file.
All sensitive values (tokens, API keys) must be in .env — never hardcoded.
"""
import os
try:
    from dotenv import load_dotenv
    _config_dir = os.path.dirname(os.path.abspath(__file__))
    _env_path = os.path.join(_config_dir, '.env')
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
    else:
        _parent_env = os.path.join(os.path.dirname(_config_dir), '.env')
        if os.path.exists(_parent_env):
            load_dotenv(_parent_env)
        else:
            load_dotenv()
except ImportError:
    pass


# ─── Safe env-var helpers ─────────────────────────────────────────────────────
# GitHub Actions sets missing secrets to "" (empty string).
# Plain float("") / int("") crash at import time — use these helpers instead.

def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name, "")
    return value.strip() or default


def _env_float(name: str, default: float) -> float:
    try:
        v = os.getenv(name, "").strip()
        return float(v) if v else default
    except (ValueError, TypeError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        v = os.getenv(name, "").strip()
        return int(v) if v else default
    except (ValueError, TypeError):
        return default


def _normalize_tg_url(value: str, fallback_username: str) -> str:
    value = (value or "").strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    username = value.lstrip("@") if value else fallback_username.lstrip("@")
    return f"https://t.me/{username}"


# ─── Core ─────────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
DATABASE_URL: str = os.getenv("DATABASE_URL", os.getenv("BOT_DATABASE_URL", "sqlite+aiosqlite:///smm_bot.db"))

ADMIN_IDS: list[int] = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
]
OWNER_IDS: list[int] = [
    int(x.strip()) for x in os.getenv("OWNER_IDS", "6764721397").split(",") if x.strip().isdigit()
]

# ─── Bot identity ─────────────────────────────────────────────────────────────
BOT_NAME: str           = _env_str("BOT_NAME", "𝑲𝒊𝒓𝒂 | كيرا")
BOT_CHANNEL: str        = _env_str("BOT_CHANNEL", "TBEKTl")
SUPPORT_USERNAME: str   = _env_str("SUPPORT_USERNAME", "@R_I_Ie")
ACTIVATIONS_CHANNEL: str = _env_str("ACTIVATIONS_CHANNEL", "@TBEKTK")

BOT_CHANNEL_URL: str = _normalize_tg_url(_env_str("BOT_CHANNEL_URL"), BOT_CHANNEL)
ACTIVATIONS_CHANNEL_URL: str = _normalize_tg_url(_env_str("ACTIVATIONS_CHANNEL_URL"), ACTIVATIONS_CHANNEL)

# ─── Payment gateways ─────────────────────────────────────────────────────────
BINANCE_PAY_ID: str     = os.getenv("BINANCE_PAY_ID", "").strip()
BINANCE_API_KEY: str    = os.getenv("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET: str = os.getenv("BINANCE_API_SECRET", "").strip()
BINANCE_PAY_MERCHANT_ENABLED: bool = os.getenv(
    "BINANCE_PAY_MERCHANT_ENABLED", "0"
).strip().lower() in {"1", "true", "yes", "on"}
FAZERCARDS_API_KEY: str = os.getenv("FAZERCARDS_API_KEY", "").strip()

# ─── Tunable numbers ─────────────────────────────────────────────────────────
REFERRAL_REWARD: float    = _env_float("REFERRAL_REWARD", 0.1)
SERVICES_PER_PAGE: int    = _env_int("SERVICES_PER_PAGE", 8)
ADMIN_PER_PAGE: int       = _env_int("ADMIN_PER_PAGE", 10)
HTTP_TIMEOUT_SECONDS: int = _env_int("HTTP_TIMEOUT_SECONDS", 15)
DEFAULT_MARKUP_PCT: float = _env_float("DEFAULT_MARKUP_PCT", 30.0)
SYNC_INTERVAL: int        = _env_int("SYNC_INTERVAL_MIN", 10) * 60
ORDER_UPDATE_INTERVAL: int = _env_int("ORDER_UPDATE_INTERVAL_SEC", 60)

# ─── Infrastructure ───────────────────────────────────────────────────────────
PROXY_URL: str  = os.getenv("PROXY_URL", "").strip()
REDIS_URL: str  = os.getenv("REDIS_URL", "").strip()
SETTINGS_FILE: str = os.path.join(os.path.dirname(__file__), "bot_settings.json")
