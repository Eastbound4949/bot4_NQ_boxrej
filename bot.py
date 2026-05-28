"""
bot.py — NQ Prev-Day-High Bounce Bot
Railway worker: runs continuously, checks for signals every hour during session.

Strategy: 10yr backtest (2016-2026) +187% return, 8.1% MaxDD, 45% WR, Sharpe 1.11
Instrument: NQ=F (Nasdaq 100 futures / US100 CFD)
Timeframe: Daily ref + 1h execution
"""

import csv
import logging
import os
import sys
from datetime import datetime, date
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler

# ── Config ────────────────────────────────────────────────────────────────────
if not os.path.exists("config.py"):
    import shutil
    shutil.copy("config.example.py", "config.py")

import config
import notifier
import state
from data_feed import fetch_daily, fetch_hourly, get_prev_day_high, get_session_bars
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
strategy = PrevDayHighStrategy()
bot_state: state.BotState = None


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

    log.info(
        f"TRADE CLOSED | {outcome.upper()} | "
        f"entry={bot_state.entry_price:.1f} exit={exit_price:.1f} | "
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
    bot_state.days_in_trade = 0
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
    bot_state.days_in_trade = 0
    bot_state.trades_today += 1
    state.save(bot_state)

    log.info(
        f"TRADE OPEN | entry={signal.entry_price:.1f} "
        f"stop={signal.stop_price:.1f} target={signal.target_price:.1f} "
        f"risk=${dollar_risk:.2f}"
    )
    _notify(notifier.fmt_entry(
        config.TICKER, signal.entry_price, signal.stop_price,
        signal.target_price, signal.risk_pts, signal.prev_high,
        dollar_risk, bot_state.balance
    ))


def _session_reset():
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
    bot_state.last_session_date = today_str
    state.save(bot_state)
    log.info(f"New session: {today_str} | balance=${bot_state.balance:,.2f}")


def check_signal():
    """Main logic — called by scheduler every hour."""
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

    # Fetch data
    try:
        daily = fetch_daily(days=7)
        hourly = fetch_hourly(days=4)
    except Exception as e:
        log.error(f"Data fetch failed: {e}")
        return

    prev_high = get_prev_day_high(daily)
    if prev_high is None:
        log.warning("Could not determine prev_day_high")
        return

    # ── Check open trade ─────────────────────────────────────────────────────
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

        bot_state.days_in_trade += 1
        if bot_state.days_in_trade >= config.MAX_BARS_IN_TRADE:
            _close_trade("timeout", cl)
            return

        log.info(
            f"IN TRADE | day {bot_state.days_in_trade}/{config.MAX_BARS_IN_TRADE} | "
            f"current={cl:.1f} stop={bot_state.stop_price:.1f} target={bot_state.target_price:.1f}"
        )
        state.save(bot_state)
        return

    # ── Look for new signal ──────────────────────────────────────────────────
    daily_loss_pct = abs(bot_state.daily_pnl / bot_state.balance * 100) if bot_state.daily_pnl < 0 else 0
    if bot_state.trades_today >= config.MAX_TRADES_PER_DAY:
        log.info(f"Max trades/day reached ({config.MAX_TRADES_PER_DAY})")
        return
    if daily_loss_pct >= config.MAX_DAILY_LOSS_PCT:
        log.info(f"Daily loss limit hit ({daily_loss_pct:.1f}%)")
        return

    today_bars = get_session_bars(hourly, date.today())
    signal = strategy.find_signal(today_bars, prev_high)

    if signal:
        log.info(f"SIGNAL FOUND | {signal.reason}")
        _open_trade(signal)
    else:
        log.info(
            f"No signal | prev_high={prev_high:.1f} | "
            f"session bars={len(today_bars)} | "
            f"balance=${bot_state.balance:,.2f}"
        )


def main():
    global bot_state

    log.info("=" * 55)
    log.info(f"  NQ PREV-DAY-HIGH BOUNCE BOT")
    log.info(f"  Ticker:  {config.TICKER}")
    log.info(f"  Mode:    {'PAPER TRADING' if config.PAPER_TRADING else 'LIVE TRADING'}")
    log.info("=" * 55)

    bot_state = state.load(config.ACCOUNT_SIZE)
    log.info(f"State loaded | balance=${bot_state.balance:,.2f} | in_trade={bot_state.in_trade}")

    _notify(notifier.fmt_startup(config.TICKER, bot_state.balance, config.PAPER_TRADING))

    scheduler = BlockingScheduler(timezone=config.TIMEZONE)
    scheduler.add_job(
        check_signal,
        trigger="cron",
        minute=2,           # fire at HH:02 every hour (gives data time to update)
        hour="*",
        day_of_week="mon-fri",
        id="signal_check",
    )

    log.info("Scheduler started — checking every hour at HH:02")
    check_signal()  # run immediately on startup

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped.")
        state.save(bot_state)


if __name__ == "__main__":
    main()
