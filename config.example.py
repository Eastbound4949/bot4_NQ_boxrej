"""
config.example.py — copy to config.py and fill in values.
On Railway: set as environment variables in the Variables tab (never commit real keys).

cp config.example.py config.py
"""

import os

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")

# ── Instrument ────────────────────────────────────────────────────────────────
TICKER = os.environ.get("TICKER", "NQ=F")          # NQ futures (Yahoo Finance)
NAME   = os.environ.get("NAME",   "NQ Prev-Day-High Bounce")

# ── Strategy parameters (optimised: 2yr TF×RRR sweep, daily bars win Calmar=21) ─
# Previous: RR=2.5, Touch=0.2%, MaxBars=3 → +29.5% / 2yr, Calmar=5.28
# Optimal : RR=3.5, Touch=0.5%, MaxBars=2 → +95.1% / 2yr, Calmar=21.01
TOUCH_THRESHOLD     = float(os.environ.get("TOUCH_THRESHOLD",     "0.005"))   # 0.50%
RR_TARGET           = float(os.environ.get("RR_TARGET",           "3.5"))
MAX_BARS_IN_TRADE   = int(os.environ.get("MAX_BARS_IN_TRADE",     "2"))       # days
MIN_MOVE_ABOVE_OPEN = float(os.environ.get("MIN_MOVE_ABOVE_OPEN", "0.002"))   # 0.20%

# ── Session (Eastern Time — NQ regular hours) ─────────────────────────────────
SESSION_START = os.environ.get("SESSION_START", "09:00")
SESSION_END   = os.environ.get("SESSION_END",   "16:30")
TIMEZONE      = os.environ.get("TIMEZONE",      "America/New_York")

# ── Risk management ───────────────────────────────────────────────────────────
PAPER_TRADING       = os.environ.get("PAPER_TRADING", "true").lower() == "true"
ACCOUNT_SIZE        = float(os.environ.get("ACCOUNT_SIZE",    "1000.0"))
RISK_PER_TRADE_PCT  = float(os.environ.get("RISK_PER_TRADE_PCT", "2.5"))     # % of account — risk sweep: 2.5% = best CAGR (78.7%) under 20% DD limit
MAX_DAILY_LOSS_PCT  = float(os.environ.get("MAX_DAILY_LOSS_PCT",  "5.0"))     # % of account
MAX_TRADES_PER_DAY  = int(os.environ.get("MAX_TRADES_PER_DAY",   "1"))

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FILE  = os.environ.get("LOG_FILE", "trades_log.csv")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# ── Scheduler ─────────────────────────────────────────────────────────────────
CHECK_INTERVAL_MINUTES = int(os.environ.get("CHECK_INTERVAL_MINUTES", "60"))
