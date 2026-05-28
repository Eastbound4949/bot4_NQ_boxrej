"""
Backtest runner for PrevDayHigh Bounce strategy.
Usage: python backtest.py
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

from config import CONFIG
from data_feed import fetch_historical, get_prev_day_high, get_session_bars
from strategy import PrevDayHighStrategy


def run_backtest(
    ticker: str = None,
    period: str = "2y",
    risk_pct: float = None,
    account_size: float = None,
) -> dict:
    cfg = CONFIG
    t = ticker or cfg.ticker
    risk_pct = risk_pct or cfg.risk_per_trade_pct
    account = account_size or cfg.account_size

    print(f"Fetching data for {t}...")
    daily, hourly = fetch_historical(t, period)

    strategy = PrevDayHighStrategy(cfg)
    trades = []
    equity = account

    trading_days = daily.index[1:]

    for i, day in enumerate(trading_days):
        prev_high = get_prev_day_high(daily, day)
        if prev_high is None:
            continue

        day_bars = get_session_bars(hourly, day.date())
        if len(day_bars) < 3:
            continue

        signal = strategy.find_signal(day_bars, prev_high)
        if signal is None:
            continue

        # Find index of entry bar in day_bars
        signal_time = pd.Timestamp(signal.signal_bar_time)
        try:
            signal_idx = day_bars.index.get_loc(signal_time)
        except KeyError:
            matches = day_bars.index[day_bars.index <= signal_time]
            if matches.empty:
                continue
            signal_idx = len(day_bars.index[:day_bars.index.get_loc(matches[-1])])

        bars_after = day_bars.iloc[signal_idx + 2:]  # +2: skip signal bar and entry bar

        result = strategy.simulate_trade(signal, bars_after, str(day.date()))

        # Position sizing: risk_pct of current equity
        dollar_risk = equity * (risk_pct / 100)
        position_value = dollar_risk / signal.risk_pts * signal.entry_price if signal.risk_pts > 0 else 0
        dollar_pnl = result.pnl_r * dollar_risk

        equity += dollar_pnl
        equity = max(equity, 0)

        trades.append({
            "date": result.date,
            "prev_high": signal.prev_high,
            "entry": signal.entry_price,
            "stop": signal.stop_price,
            "target": signal.target_price,
            "risk_pts": signal.risk_pts,
            "outcome": result.outcome,
            "pnl_r": result.pnl_r,
            "dollar_risk": round(dollar_risk, 2),
            "dollar_pnl": round(dollar_pnl, 2),
            "equity": round(equity, 2),
        })

    if not trades:
        return {"error": "No trades found"}

    df = pd.DataFrame(trades)
    wins = df[df["pnl_r"] > 0]
    losses = df[df["pnl_r"] <= 0]
    total = len(df)

    # Equity curve stats
    peak = account
    max_dd_abs = 0
    max_dd_pct = 0
    for eq in df["equity"]:
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_pct = dd / peak * 100
        if dd > max_dd_abs:
            max_dd_abs = dd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    final_equity = df.iloc[-1]["equity"]
    total_pnl = final_equity - account
    pct_return = total_pnl / account * 100

    stats = {
        "ticker": t,
        "period": period,
        "start_account": account,
        "final_equity": round(final_equity, 2),
        "total_pnl": round(total_pnl, 2),
        "pct_return": round(pct_return, 2),
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / total * 100, 1),
        "avg_pnl_r": round(df["pnl_r"].mean(), 3),
        "total_r": round(df["pnl_r"].sum(), 2),
        "max_dd_abs": round(max_dd_abs, 2),
        "max_dd_pct": round(max_dd_pct, 2),
        "best_trade": round(df["dollar_pnl"].max(), 2),
        "worst_trade": round(df["dollar_pnl"].min(), 2),
        "trades_df": df,
    }
    return stats


def print_report(stats: dict):
    if "error" in stats:
        print(f"ERROR: {stats['error']}")
        return

    df = stats["trades_df"]
    print("=" * 55)
    print(f"  BACKTEST: {stats['ticker']} — {stats['period']}")
    print("=" * 55)
    print(f"  Account:       ${stats['start_account']:>10,.2f}")
    print(f"  Final equity:  ${stats['final_equity']:>10,.2f}")
    print(f"  Total P/L:     ${stats['total_pnl']:>10,.2f}  ({stats['pct_return']:+.1f}%)")
    print(f"  Max drawdown:  ${stats['max_dd_abs']:>10,.2f}  ({stats['max_dd_pct']:.1f}%)")
    print(f"  Total trades:  {stats['total_trades']}")
    print(f"  Win rate:      {stats['win_rate']}%")
    print(f"  Avg R/trade:   {stats['avg_pnl_r']:+.3f}R")
    print(f"  Total R:       {stats['total_r']:+.2f}R")
    print(f"  Best trade:    ${stats['best_trade']:,.2f}")
    print(f"  Worst trade:   ${stats['worst_trade']:,.2f}")
    print()
    print("  Monthly P/L:")
    df["month"] = pd.to_datetime(df["date"]).dt.to_period("M")
    monthly = df.groupby("month")["dollar_pnl"].sum().round(2)
    for month, pnl in monthly.items():
        bar = "+" * int(abs(pnl) / 50) if pnl > 0 else "-" * int(abs(pnl) / 50)
        print(f"    {month}  {pnl:>+9.2f}  {bar}")
    print("=" * 55)


if __name__ == "__main__":
    stats = run_backtest(
        ticker=CONFIG.ticker,
        period="2y",
        risk_pct=CONFIG.risk_per_trade_pct,
        account_size=CONFIG.account_size,
    )
    print_report(stats)
