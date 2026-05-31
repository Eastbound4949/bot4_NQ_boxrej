from dataclasses import dataclass
from datetime import date
from typing import Optional
import pandas as pd


@dataclass
class TradeSignal:
    direction: str
    entry_price: float
    stop_price: float
    target_price: float
    risk_pts: float
    prev_high: float
    signal_bar_time: str
    reason: str = ""


@dataclass
class TradeResult:
    signal: TradeSignal
    outcome: str
    pnl_r: float
    exit_price: float
    exit_time: str
    date: str


class PrevDayHighStrategy:
    """
    Previous Day High Bounce — Daily-bar signal, hourly trade management.
    ─────────────────────────────────────────────────────────────────────
    Signal  : yesterday HIGH >= prev_high*(1-touch), close < prev_high
    Entry   : today's market open (current price at session start)
    Stop    : yesterday's LOW
    Target  : entry + risk * RR
    Timeout : MAX_BARS_IN_TRADE trading days
    ─────────────────────────────────────────────────────────────────────
    Optimised 2yr sweep (2024-2026):
      Touch=0.5%, RR=3.5, MaxDays=2 → Calmar=21.01, +95.1%/2yr, 4.5% DD
    10yr backtest (2016-2026):
      CAGR=27.5%/yr, Sharpe=1.54, MaxDD=7.7%, PF=2.25
    """

    def __init__(self, touch_threshold: float = 0.005, rr_target: float = 3.5,
                 min_move_above_open: float = 0.002, max_bars: int = 2):
        self.touch    = touch_threshold
        self.rr       = rr_target
        self.min_move = min_move_above_open
        self.max_bars = max_bars

    # ── Daily signal (primary — for live bot) ─────────────────────────────────

    def find_daily_signal(self, daily_df: pd.DataFrame,
                          current_price: float) -> Optional[TradeSignal]:
        """
        Daily bar rejection signal.
        yesterday = rejection bar (touched prev_high zone, closed below)
        Enter at current_price ≈ today's session open.
        Stop: yesterday's low.
        """
        today_date = date.today()
        past = daily_df[daily_df.index.date < today_date]
        if len(past) < 2:
            return None

        yesterday = past.iloc[-1]
        two_ago   = past.iloc[-2]
        prev_high = float(two_ago["High"])

        yh = float(yesterday["High"])
        yl = float(yesterday["Low"])
        yc = float(yesterday["Close"])
        yo = float(yesterday["Open"])

        touched  = yh >= prev_high * (1 - self.touch)
        rejected = yc < prev_high
        min_lvl  = prev_high >= yo * (1 + self.min_move)

        if not (touched and rejected and min_lvl):
            return None

        entry = current_price
        stop  = yl
        risk  = entry - stop

        if risk <= 0 or risk > entry * 0.025:
            return None

        return TradeSignal(
            direction="long",
            entry_price=round(entry, 2),
            stop_price=round(stop, 2),
            target_price=round(entry + risk * self.rr, 2),
            risk_pts=round(risk, 2),
            prev_high=round(prev_high, 2),
            signal_bar_time=str(yesterday.name.date()),
            reason=(f"Daily rejection: prev_high={prev_high:.1f}, "
                    f"yesterday H={yh:.1f} C={yc:.1f} L={yl:.1f}, "
                    f"entry={entry:.1f} stop={yl:.1f} target={entry + risk * self.rr:.1f}"),
        )

    # ── Intraday signal (legacy — kept for backtesting via backtest.py) ───────

    def find_signal(self, bars: pd.DataFrame, prev_high: float) -> Optional[TradeSignal]:
        """
        1h session-bar signal (original hourly implementation).
        Kept for compatibility with backtest.py / bt_nq.py.
        """
        if len(bars) < 3 or prev_high is None:
            return None

        session_open = float(bars.iloc[0]["Open"])
        if prev_high < session_open * (1 + self.min_move):
            return None

        in_rejection = False

        for j in range(len(bars) - 1):
            bar = bars.iloc[j]
            close = float(bar["Close"])
            high  = float(bar["High"])
            low   = float(bar["Low"])
            open_ = float(bar["Open"])

            if not in_rejection:
                if high >= prev_high * (1 - self.touch) and close < prev_high:
                    in_rejection = True
                    continue

            if in_rejection and close > open_:
                if j + 1 >= len(bars):
                    break
                next_bar = bars.iloc[j + 1]
                entry = float(next_bar["Open"])
                stop  = low
                risk  = entry - stop

                if risk <= 0 or risk > entry * 0.02:
                    in_rejection = False
                    continue

                return TradeSignal(
                    direction="long",
                    entry_price=round(entry, 2),
                    stop_price=round(stop, 2),
                    target_price=round(entry + risk * self.rr, 2),
                    risk_pts=round(risk, 2),
                    prev_high=round(prev_high, 2),
                    signal_bar_time=str(bars.index[j]),
                    reason=f"1h rejection at prev_high={prev_high:.1f}, green bar at {bars.index[j]}",
                )

        return None

    def simulate_trade(self, signal: TradeSignal, bars_after: pd.DataFrame,
                       date_str: str) -> TradeResult:
        outcome = "timeout"
        pnl_r = 0.0
        exit_price = signal.entry_price
        exit_time = "timeout"

        for _, bar in bars_after.iloc[:self.max_bars].iterrows():
            if float(bar["Low"]) <= signal.stop_price:
                outcome = "loss"; pnl_r = -1.0
                exit_price = signal.stop_price; exit_time = str(bar.name)
                break
            if float(bar["High"]) >= signal.target_price:
                outcome = "win"; pnl_r = self.rr
                exit_price = signal.target_price; exit_time = str(bar.name)
                break
        else:
            if not bars_after.empty:
                exit_price = float(bars_after.iloc[min(self.max_bars, len(bars_after)) - 1]["Close"])
                exit_time  = str(bars_after.index[min(self.max_bars, len(bars_after)) - 1])
                pnl_r = (exit_price - signal.entry_price) / signal.risk_pts if signal.risk_pts else 0

        return TradeResult(
            signal=signal, outcome=outcome, pnl_r=round(pnl_r, 3),
            exit_price=round(exit_price, 2), exit_time=exit_time, date=date_str,
        )
