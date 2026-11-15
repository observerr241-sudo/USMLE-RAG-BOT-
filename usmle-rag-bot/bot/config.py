"""Environment configuration. Importing this module never raises; call validate() at startup."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _csv(name: str) -> list[str]:
    return [p.strip() for p in os.getenv(name, "").split(",") if p.strip()]


def _int_csv(name: str) -> list[int]:
    out: list[int] = []
    for p in _csv(name):
        try:
            out.append(int(p))
        except ValueError:
            raise SystemExit(f"{name} contains a non-integer value: {p!r}")
    return out


TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_IDS: set[int] = set(_int_csv("ADMIN_IDS"))
MONGODB_URI: str = os.getenv("MONGODB_URI", "").strip()
MONGODB_DB: str = os.getenv("MONGODB_DB", "usmle_rag_db").strip() or "usmle_rag_db"

# Comma-separated Gemini keys (duplicates removed, order preserved)
GEMINI_API_KEYS: list[str] = list(dict.fromkeys(_csv("GEMINI_API_KEYS")))

GENERATION_MODEL: str = os.getenv("GENERATION_MODEL", "gemini-3.6-flash")
EMBEDDING_MODEL: str = "gemini-embedding-001"
EMBEDDING_DIM: int = 768

# Gemini rotator tuning (free tier of gemini-3.6-flash is roughly 10 RPM per key)
ROTATOR_DB: str = os.getenv("ROTATOR_DB", "data/rotator.db")
ROTATOR_RPM_PER_KEY: int = int(os.getenv("ROTATOR_RPM_PER_KEY", "10"))
ROTATOR_MAX_CONCURRENT_PER_KEY: int = int(os.getenv("ROTATOR_MAX_CONCURRENT_PER_KEY", "2"))

# Paywall text
PRICE_TEXT: str = os.getenv("PRICE_TEXT", "200 BDT/month")
PAYMENT_INSTRUCTIONS: str = os.getenv("PAYMENT_INSTRUCTIONS", "").strip()  # e.g. "bKash (Personal): 01XXXXXXXXX"

# Optional webhook mode (leave WEBHOOK_BASE_URL empty to use long polling)
WEBHOOK_BASE_URL: str = os.getenv("WEBHOOK_BASE_URL", "").strip().rstrip("/")
WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/telegram/webhook")
WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "").strip()
WEBAPP_HOST: str = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT: int = int(os.getenv("PORT", "8080"))


def validate(require_bot: bool = True) -> None:
    missing = []
    if require_bot and not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if require_bot and not ADMIN_IDS:
        missing.append("ADMIN_IDS")
    if not MONGODB_URI:
        missing.append("MONGODB_URI")
    if not GEMINI_API_KEYS:
        missing.append("GEMINI_API_KEYS")
    if missing:
        raise SystemExit("Missing required environment variables: " + ", ".join(missing))
