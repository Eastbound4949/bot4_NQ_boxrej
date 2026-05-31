"""
bot.py — NQ Prev-Day-High Bounce Bot (DAILY BAR STRATEGY)
Railway worker: runs hourly scheduler during NYSE session.

Strategy (optimised 2yr sweep, 2024-2026):
  RR=3.5  Touch=0.5%  MaxDays=2
  2yr: +95.1% return, 4.5% MaxDD, Calmar=21.01, WR=54.1%
  10yr CAGR: 27.5%/yr | Sharpe: 1.54 | PF: 2.25

Signal logic:
  Yesterday: HIGH >= prev_day_high*(1-0.5%), close < prev_day_high  (rejection)
  Today at open: enter LONG at current market price
  Stop: yesterday's LOW
  Target: entry + risk * 3.5
  Timeout: 2 trading days

Instrument: NQ=F (Nasdaq-100 Futures via Yahoo Finance)
"""

import csv
import logging
import os
import sys
from datetime import datetime, date
from zoneinfo import ZoneInfo

import numpy as np
from apscheduler.schedulers.blocking import BlockingScheduler

# ── Config ────────────────────────────────────────────────────────────────────
if not os.path.exists("config.py"):
    import shutil
    shutil.copy("config.example.py", "config.py")

import config
import notifier
import state
from data_feed import fetch_daily, fetch_hourly, get_latest_price
from strategy import PrevDayHighStrategy, TradeSignal

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Globals ───────────────────────────────────────────────────────────────────
TZ       = ZoneInfo(config.TIMEZONE)
strategy = PrevDayHighStrategy(
    touch_threshold=config.TOUCH_THRESHOLD,
    rr_target=config.RR_TARGET,
    min_move_above_open=config.MIN_MOVE_ABOVE_OPEN,
    max_bars=config.MAX_BARS_IN_TRADE,
)
bot_state: state.BotState = None


def _trading_days_since(entry_date_str: str) -> int:
    """Number of trading (business) days from entry_date to today."""
    if not entry_date_str:
        return 0
    try:
        entry = date.fromisoformat(entry_date_str)
        today = date.today()
        return max(0, int(np.busday_count(entry, today)))
    except Exception:
        return 0


def _notify(text: str):
    notifier.send(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, text)


def _log_trade(outcome: str, entry: float, exit_price: float, pnl_r: float,
               dollar_pnl: float, balance: float):
    file_exists = os.path.isfile(config.LOG_FILE)
    with open(config.LOG_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(["timestamp", "ticker", "entry", "stop", "target",
                        "exit_price", "outcome", "pnl_r", "dollar_pnl", "balance"])
        w.writerow([
            datetime.now(TZ).isoformat(),
            config.TICKER,
            round(entry, 2),
            round(bot_state.stop_price, 2),
            round(bot_state.target_price, 2),
            round(exit_price, 2),
            outcome,
            round(pnl_r, 3),
            round(dollar_pnl, 2),
            round(balance, 2),
        ])


def _close_trade(outcome: str, exit_price: float):
    global bot_state
    risk = bot_state.dollar_risk
    pnl_r = (
        config.RR_TARGET if outcome == "win"
        else (-1.0 if outcome == "loss"
              else (exit_price - bot_state.entry_price) / bot_state.risk_pts)
    )
    dollar_pnl = pnl_r * risk
    bot_state.balance += dollar_pnl
    bot_state.balance = max(bot_state.balance, 0.0)
    bot_state.daily_pnl += dollar_pnl
    bot_state.total_trades += 1
    if pnl_r > 0:
        bot_state.total_wins += 1

    days_held = _trading_days_since(bot_state.entry_date)
    log.info(
        f"TRADE CLOSED | {outcome.upper()} | "
        f"entry={bot_state.entry_price:.1f} exit={exit_price:.1f} | "
        f"held {days_held}d | "
        f"P/L={pnl_r:+.2f}R = ${dollar_pnl:+.2f} | balance=${bot_state.balance:,.2f}"
    )
    _notify(notifier.fmt_exit(
        config.TICKER, outcome, bot_state.entry_price,
        exit_price, pnl_r, dollar_pnl, bot_state.balance
    ))
    _log_trade(outcome, bot_state.entry_price, exit_price, pnl_r, dollar_pnl, bot_state.balance)

    bot_state.in_trade = False
    bot_state.entry_price = 0.0
    bot_state.stop_price = 0.0
    bot_state.target_price = 0.0
    bot_state.risk_pts = 0.0
    bot_state.dollar_risk = 0.0
    bot_state.entry_date = ""
    state.save(bot_state)


def _open_trade(signal: TradeSignal):
    global bot_state
    dollar_risk = bot_state.balance * (config.RISK_PER_TRADE_PCT / 100)
    bot_state.in_trade = True
    bot_state.entry_price = signal.entry_price
    bot_state.stop_price = signal.stop_price
    bot_state.target_price = signal.target_price
    bot_state.risk_pts = signal.risk_pts
    bot_state.dollar_risk = dollar_risk
    bot_state.prev_high = signal.prev_high
    bot_state.entry_date = str(date.today())
    bot_state.trades_today += 1
    state.save(bot_state)

    log.info(
        f"TRADE OPEN | entry={signal.entry_price:.1f} "
        f"stop={signal.stop_price:.1f} target={signal.target_price:.1f} "
        f"risk_pts={signal.risk_pts:.1f} dollar_risk=${dollar_risk:.2f}"
    )
    _notify(notifier.fmt_entry(
        config.TICKER, signal.entry_price, signal.stop_price,
        signal.target_price, signal.risk_pts, signal.prev_high,
        dollar_risk, bot_state.balance
    ))


def _session_reset():
    """Reset daily counters when a new trading day begins."""
    global bot_state
    today_str = str(date.today())
    if bot_state.last_session_date == today_str:
        return
    if bot_state.trades_today > 0:
        _notify(notifier.fmt_daily_summary(
            config.TICKER, bot_state.last_session_date,
            bot_state.trades_today, bot_state.daily_pnl, bot_state.balance
        ))
    bot_state.trades_today = 0
    bot_state.daily_pnl = 0.0
    bot_state.signal_checked_today = False   # allow fresh daily signal check
    bot_state.last_session_date = today_str
    state.save(bot_state)
    log.info(f"New session: {today_str} | balance=${bot_state.balance:,.2f}")


def check_signal():
    """Main logic — called by scheduler every hour during session."""
    global bot_state

    now = datetime.now(TZ)
    _session_reset()

    # Outside session hours — skip
    sh, sm = map(int, config.SESSION_START.split(":"))
    eh, em = map(int, config.SESSION_END.split(":"))
    in_session = (
        (now.hour > sh or (now.hour == sh and now.minute >= sm))
        and (now.hour < eh or (now.hour == eh and now.minute <= em))
        and now.weekday() < 5   # Mon-Fri only
    )
    if not in_session:
        log.debug(f"Outside session ({now.strftime('%H:%M %Z')}) — skipping")
        return

    # Fetch hourly data for trade management
    try:
        hourly = fetch_hourly(days=4)
    except Exception as e:
        log.error(f"Hourly data fetch failed: {e}")
        return

    # ── Manage open trade (stop/target/timeout) ──────────────────────────────
    if bot_state.in_trade:
        latest = hourly.iloc[-1]
        lo = float(latest["Low"])
        hi = float(latest["High"])
        cl = float(latest["Close"])

        if lo <= bot_state.stop_price:
            _close_trade("loss", bot_state.stop_price)
            return

        if hi >= bot_state.target_price:
            _close_trade("win", bot_state.target_price)
            return

        days_held = _trading_days_since(bot_state.entry_date)
        if days_held >= config.MAX_BARS_IN_TRADE:
            _close_trade("timeout", cl)
            return

        log.info(
            f"IN TRADE | day {days_held}/{config.MAX_BARS_IN_TRADE} | "
            f"price={cl:.1f} stop={bot_state.stop_price:.1f} "
            f"target={bot_state.target_price:.1f}"
        )
        state.save(bot_state)
        return

    # ── Look for daily rejection signal (once per session) ───────────────────
    if bot_state.signal_checked_today:
        log.debug("Daily signal already checked today")
        return

    if bot_state.trades_today >= config.MAX_TRADES_PER_DAY:
        log.info(f"Max trades/day reached ({config.MAX_TRADES_PER_DAY})")
        bot_state.signal_checked_today = True
        state.save(bot_state)
        return

    daily_loss_pct = (abs(bot_state.daily_pnl) / bot_state.balance * 100
                      if bot_state.daily_pnl < 0 else 0)
    if daily_loss_pct >= config.MAX_DAILY_LOSS_PCT:
        log.info(f"Daily loss limit hit ({daily_loss_pct:.1f}%)")
        bot_state.signal_checked_today = True
        state.save(bot_state)
        return

    try:
        daily = fetch_daily(days=7)
        current_price = get_latest_price(config.TICKER)
    except Exception as e:
        log.error(f"Daily data fetch failed: {e}")
        return

    if current_price is None:
        log.warning("Could not fetch current price")
        return

    signal = strategy.find_daily_signal(daily, current_price)
    bot_state.signal_checked_today = True
    state.save(bot_state)

    if signal:
        log.info(f"DAILY SIGNAL | {signal.reason}")
        _open_trade(signal)
    else:
        log.info(
            f"No signal | price={current_price:.1f} | "
            f"balance=${bot_state.balance:,.2f}"
        )


def main():
    global bot_state

    log.info("=" * 60)
    log.info(f"  NQ PREV-DAY-HIGH BOUNCE BOT  (Daily Bar Strategy)")
    log.info(f"  Ticker:    {config.TICKER}")
    log.info(f"  Mode:      {'PAPER TRADING' if config.PAPER_TRADING else 'LIVE TRADING'}")
    log.info(f"  RR:        {config.RR_TARGET}")
    log.info(f"  Touch:     {config.TOUCH_THRESHOLD*100:.1f}%")
    log.info(f"  Max days:  {config.MAX_BARS_IN_TRADE}")
    log.info(f"  Risk/trade:{config.RISK_PER_TRADE_PCT}%")
    log.info("=" * 60)

    bot_state = state.load(config.ACCOUNT_SIZE)
    log.info(f"State loaded | balance=${bot_state.balance:,.2f} | in_trade={bot_state.in_trade}")

    _notify(notifier.fmt_startup(
        config.TICKER, bot_state.balance, config.PAPER_TRADING,
        config.RR_TARGET, config.RISK_PER_TRADE_PCT
    ))

    scheduler = BlockingScheduler(timezone=config.TIMEZONE)
    scheduler.add_job(
        check_signal,
        trigger="cron",
        minute=2,           # fire at HH:02 every hour
        hour="*",
        day_of_week="mon-fri",
        id="signal_check",
    )

    log.info("Scheduler started — checking hourly at HH:02")
    check_signal()  # run immediately on startup

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")
        state.save(bot_state)


if __name__ == "__main__":
    main()
