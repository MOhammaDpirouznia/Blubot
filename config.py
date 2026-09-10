import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Telegram Bot
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "BluPalBot")
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))

# Database
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{BASE_DIR}/blupal.db")

# Server & Public URLs
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("PORT") or os.getenv("SERVER_PORT", "8000"))
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

# Security & Encryption Key (Fernet 32-byte urlsafe base64)
# If not set, generate or use fallback for development
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "u7BfQzF3lQ2e4aP5f7g9h1j3k5m7n9p1q3r5t7v9x1y=")

# Economic & Commission Settings (BluPal Style)
DEFAULT_FEE_PERCENT = float(os.getenv("DEFAULT_FEE_PERCENT", "2.0"))  # 2%
DEFAULT_FEE_CAP = int(os.getenv("DEFAULT_FEE_CAP", "350000"))  # 35,000 Tomans = 350,000 Rials
FREE_TRIAL_DAYS = int(os.getenv("FREE_TRIAL_DAYS", "30"))  # First 30 days free
FREE_TRIAL_TRANSACTIONS = int(os.getenv("FREE_TRIAL_TRANSACTIONS", "50"))
MIN_WALLET_BALANCE_ALERT = int(os.getenv("MIN_WALLET_BALANCE_ALERT", "500000"))  # 50,000 Tomans

# Matching Engine & Poller
INVOICE_TTL_MINUTES = int(os.getenv("INVOICE_TTL_MINUTES", "20"))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "10"))
WEBHOOK_TIMEOUT_SECONDS = int(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "10"))
