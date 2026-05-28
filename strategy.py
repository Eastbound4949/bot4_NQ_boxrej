from dataclasses import dataclass
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
    Previous Day High Bounce
    ────────────────────────
    1. Previous day HIGH = key resistance level
    2. Daily/1h bar touches within TOUCH_THRESHOLD of that level and closes below → rejection
    3. Next bar is green (close > open) → entry signal
    4. Enter LONG at next bar's open
    5. Stop: below signal bar's low
    6. Target: entry + risk * RR_TARGET
    7. Exit: target / stop / MAX_BARS timeout
    """

    def __init__(self, touch_threshold: float = 0.002, rr_target: float = 2.5,
                 min_move_above_open: float = 0.002, max_bars: int = 3):
        self.touch = touch_threshold
        self.rr = rr_target
        self.min_move = min_move_above_open
        self.max_bars = max_bars

    def find_signal(self, bars: pd.DataFrame, prev_high: float) -> Optional[TradeSignal]:
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
                    reason=f"Rejection at prev_high={prev_high:.1f}, green bar at {bars.index[j]}",
                )

        return None

    def simulate_trade(self, signal: TradeSignal, bars_after: pd.DataFrame, date: str) -> TradeResult:
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
                exit_time = str(bars_after.index[min(self.max_bars, len(bars_after)) - 1])
                pnl_r = (exit_price - signal.entry_price) / signal.risk_pts if signal.risk_pts else 0

        return TradeResult(
            signal=signal, outcome=outcome, pnl_r=round(pnl_r, 3),
            exit_price=round(exit_price, 2), exit_time=exit_time, date=date,
        )
