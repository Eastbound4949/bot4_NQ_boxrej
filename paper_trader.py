"""
Paper trading engine — runs the strategy live using yfinance data,
simulates order execution, logs trades to CSV.
"""
import csv
import os
import time
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from config import CONFIG
from data_feed import fetch_daily, fetch_hourly, get_prev_day_high, get_session_bars
from strategy import PrevDayHighStrategy, TradeSignal

logging.basicConfig(level=getattr(logging, CONFIG.log_level), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


class PaperAccount:
    def __init__(self, starting_balance: float = None):
        self.balance = starting_balance or CONFIG.account_size
        self.starting_balance = self.balance
        self.open_trade: TradeSignal | None = None
        self.entry_price: float | None = None
        self.trades_today: int = 0
        self.daily_pnl: float = 0.0

    def can_trade(self) -> bool:
        daily_loss_pct = abs(self.daily_pnl / self.starting_balance * 100) if self.daily_pnl < 0 else 0
        return (
            self.open_trade is None
            and self.trades_today < CONFIG.max_trades_per_day
            and daily_loss_pct < CONFIG.max_daily_loss_pct
        )

    def dollar_risk(self) -> float:
        return self.balance * (CONFIG.risk_per_trade_pct / 100)

    def open_position(self, signal: TradeSignal):
        self.open_trade = signal
        self.entry_price = signal.entry_price
        self.trades_today += 1
        log.info(
            f"[PAPER] ENTRY LONG @ {signal.entry_price:.2f} | "
            f"Stop {signal.stop_price:.2f} | Target {signal.target_price:.2f} | "
            f"Risk ${self.dollar_risk():.0f}"
        )

    def check_exit(self, current_high: float, current_low: float) -> str | None:
        if self.open_trade is None:
            return None
        if current_low <= self.open_trade.stop_price:
            return "loss"
        if current_high >= self.open_trade.target_price:
            return "win"
        return None

    def close_position(self, outcome: str, exit_price: float, log_file: str):
        if self.open_trade is None:
            return
        risk = self.dollar_risk()
        pnl_r = CONFIG.rr_target if outcome == "win" else (-1.0 if outcome == "loss" else
                (exit_price - self.entry_price) / self.open_trade.risk_pts)
        dollar_pnl = pnl_r * risk
        self.balance += dollar_pnl
        self.daily_pnl += dollar_pnl

        log.info(
            f"[PAPER] EXIT {outcome.upper()} @ {exit_price:.2f} | "
            f"P/L: {pnl_r:+.2f}R = ${dollar_pnl:+.2f} | Balance: ${self.balance:,.2f}"
        )
        self._log_trade(outcome, exit_price, pnl_r, dollar_pnl, log_file)
        self.open_trade = None
        self.entry_price = None

    def reset_daily(self):
        self.trades_today = 0
        self.daily_pnl = 0.0

    def _log_trade(self, outcome, exit_price, pnl_r, dollar_pnl, log_file):
        file_exists = os.path.isfile(log_file)
        with open(log_file, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "ticker", "entry", "stop", "target",
                                  "exit_price", "outcome", "pnl_r", "dollar_pnl", "balance"])
            writer.writerow([
                datetime.now().isoformat(),
                CONFIG.ticker,
                self.open_trade.entry_price if self.open_trade else "",
                self.open_trade.stop_price if self.open_trade else "",
                self.open_trade.target_price if self.open_trade else "",
                exit_price,
                outcome,
                round(pnl_r, 3),
                round(dollar_pnl, 2),
                round(self.balance, 2),
            ])


class PaperTrader:
    def __init__(self):
        self.strategy = PrevDayHighStrategy()
        self.account = PaperAccount()
        self.prev_high: float | None = None
        self.signal_found_today = False
        self.log_file = CONFIG.log_file

    def on_session_start(self):
        """Call at start of each trading session."""
        self.account.reset_daily()
        self.signal_found_today = False

        daily = fetch_daily(days=5)
        self.prev_high = get_prev_day_high(daily)
        log.info(f"Session start | Prev day high: {self.prev_high} | Balance: ${self.account.balance:,.2f}")

    def on_new_bar(self, hourly_df):
        """Call after each new 1h bar closes."""
        if self.prev_high is None:
            return

        tz = ZoneInfo(CONFIG.timezone)
        today = datetime.now(tz).date()
        day_bars = get_session_bars(hourly_df, today)

        # Check exit first if in trade
        if self.account.open_trade is not None:
            latest = hourly_df.iloc[-1]
            outcome = self.account.check_exit(float(latest["High"]), float(latest["Low"]))
            if outcome:
                self.account.close_position(outcome, float(latest["Close"]), self.log_file)
            return

        # Look for entry signal
        if not self.signal_found_today and self.account.can_trade():
            signal = self.strategy.find_signal(day_bars, self.prev_high)
            if signal:
                self.signal_found_today = True
                self.account.open_position(signal)

    def run(self, poll_interval_seconds: int = 300):
        """Main loop — polls every poll_interval_seconds (default 5 min)."""
        log.info(f"Paper trader started | Ticker: {CONFIG.ticker} | Account: ${self.account.balance:,.2f}")
        tz = ZoneInfo(CONFIG.timezone)
        last_session_date = None

        while True:
            now = datetime.now(tz)
            today = now.date()

            if last_session_date != today:
                self.on_session_start()
                last_session_date = today

            session_start_h, session_start_m = map(int, CONFIG.session_start.split(":"))
            session_end_h, session_end_m = map(int, CONFIG.session_end.split(":"))
            in_session = (
                (now.hour > session_start_h or (now.hour == session_start_h and now.minute >= session_start_m))
                and (now.hour < session_end_h or (now.hour == session_end_h and now.minute <= session_end_m))
            )

            if in_session:
                hourly = fetch_hourly(days=3)
                self.on_new_bar(hourly)

            time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    trader = PaperTrader()
    trader.run()
