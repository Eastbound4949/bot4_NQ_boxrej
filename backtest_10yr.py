"""
10-Year Backtest — Prev Day High Bounce on Daily Bars
------------------------------------------------------
Adapts 1h strategy to daily timeframe for 10yr history availability.

Strategy (daily version):
  1. Reference: previous day HIGH
  2. Signal day: HIGH >= prev_high * (1 - TOUCH) and CLOSE < prev_high  → rejection
  3. Entry day : CLOSE > OPEN (green day after rejection) → enter at OPEN
  4. Stop      : signal day LOW
  5. Target    : entry + (risk * RR)
  6. Max hold  : MAX_DAYS trading days

Run: python backtest_10yr.py
Saves: backtest_10yr_trades.csv + backtest_10yr_report.txt
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import os

# ── Parameters (optimised from 2yr 1h backtest) ──────────────────────────────
TICKER          = "NQ=F"
PERIOD          = "max"       # full available history (~23 years for NQ futures)
TARGET_YEARS    = 10          # trim to last 10 years
TOUCH_THRESHOLD = 0.002       # 0.20% — price within this % of prev_high = touching
RR_TARGET       = 2.5
MAX_DAYS        = 3           # max holding days before force-exit
MIN_MOVE        = 0.002       # prev_high must be >= 0.2% above today's open
RISK_PCT        = 1.0         # % of account risked per trade
START_CAPITAL   = 1000.0      # GBP (treated as USD-equivalent for % maths)
MAX_TRADES_DAY  = 1           # one trade per day
SAVE_DIR        = os.path.dirname(os.path.abspath(__file__))

# ── Fetch data ────────────────────────────────────────────────────────────────
print(f"Fetching {TICKER} daily data...")
raw = yf.download(TICKER, period=PERIOD, interval="1d", progress=False, auto_adjust=True)
raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
raw.index = raw.index.tz_localize(None) if raw.index.tz else raw.index
raw = raw.dropna()

# Trim to last TARGET_YEARS
cutoff = raw.index[-1] - pd.DateOffset(years=TARGET_YEARS)
df = raw[raw.index >= cutoff].copy()
print(f"Using {len(df)} trading days: {df.index[0].date()} to {df.index[-1].date()}")

# ── Backtest ──────────────────────────────────────────────────────────────────
trades = []
equity = START_CAPITAL
peak_equity = equity
max_dd_abs = 0.0
max_dd_pct = 0.0
consecutive_losses = 0
max_consec_losses = 0

in_trade = False
trade_entry = 0.0
trade_stop = 0.0
trade_target = 0.0
trade_risk_pts = 0.0
trade_entry_date = ""
trade_dollar_risk = 0.0
days_in_trade = 0

for i in range(2, len(df)):
    today     = df.iloc[i]
    yesterday = df.iloc[i - 1]  # potential signal / in-trade day
    two_ago   = df.iloc[i - 2]  # prev_day_high reference

    prev_high = float(two_ago["High"])
    today_date = str(df.index[i].date())

    # ── Check open trade exit ─────────────────────────────────────────────────
    if in_trade:
        days_in_trade += 1
        lo = float(today["Low"])
        hi = float(today["High"])
        close = float(today["Close"])

        if lo <= trade_stop:
            outcome = "loss"
            pnl_r = -1.0
            exit_price = trade_stop
        elif hi >= trade_target:
            outcome = "win"
            pnl_r = RR_TARGET
            exit_price = trade_target
        elif days_in_trade >= MAX_DAYS:
            outcome = "timeout"
            exit_price = close
            pnl_r = (exit_price - trade_entry) / trade_risk_pts if trade_risk_pts > 0 else 0
        else:
            continue  # still in trade

        dollar_pnl = pnl_r * trade_dollar_risk
        equity += dollar_pnl
        equity = max(equity, 0.0)

        # Update drawdown
        if equity > peak_equity:
            peak_equity = equity
        dd_abs = peak_equity - equity
        dd_pct = dd_abs / peak_equity * 100 if peak_equity > 0 else 0
        if dd_abs > max_dd_abs:
            max_dd_abs = dd_abs
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

        if pnl_r < 0:
            consecutive_losses += 1
            max_consec_losses = max(max_consec_losses, consecutive_losses)
        else:
            consecutive_losses = 0

        trades.append({
            "entry_date": trade_entry_date,
            "exit_date": today_date,
            "prev_high": round(prev_high, 1),
            "entry": round(trade_entry, 1),
            "stop": round(trade_stop, 1),
            "target": round(trade_target, 1),
            "outcome": outcome,
            "pnl_r": round(pnl_r, 3),
            "dollar_risk": round(trade_dollar_risk, 2),
            "dollar_pnl": round(dollar_pnl, 2),
            "equity": round(equity, 2),
        })

        in_trade = False
        days_in_trade = 0
        continue

    # ── Look for new signal ───────────────────────────────────────────────────
    if in_trade:
        continue

    # Signal condition: yesterday touched prev_high zone and closed below it
    yest_high  = float(yesterday["High"])
    yest_low   = float(yesterday["Low"])
    yest_close = float(yesterday["Close"])
    yest_open  = float(yesterday["Open"])

    touched   = yest_high >= prev_high * (1 - TOUCH_THRESHOLD)
    rejected  = yest_close < prev_high
    min_level = prev_high >= yest_open * (1 + MIN_MOVE)

    if not (touched and rejected and min_level):
        continue

    # Entry condition: today is a green candle (close > open) after rejection
    today_open  = float(today["Open"])
    today_close = float(today["Close"])
    today_low   = float(today["Low"])
    is_green = today_close > today_open

    if not is_green:
        continue

    # Entry at today's open
    entry_price = today_open
    stop_price  = yest_low
    risk_pts    = entry_price - stop_price

    if risk_pts <= 0 or risk_pts > entry_price * 0.025:
        continue

    target_price   = entry_price + (risk_pts * RR_TARGET)
    dollar_risk    = equity * (RISK_PCT / 100)

    # Check intra-bar: did stop/target get hit today?
    if float(today["Low"]) <= stop_price:
        outcome = "loss"
        pnl_r = -1.0
        exit_price = stop_price
        dollar_pnl = pnl_r * dollar_risk
        equity += dollar_pnl
        equity = max(equity, 0.0)
        if equity > peak_equity:
            peak_equity = equity
        dd_abs = peak_equity - equity
        dd_pct = dd_abs / peak_equity * 100 if peak_equity > 0 else 0
        if dd_abs > max_dd_abs: max_dd_abs = dd_abs
        if dd_pct > max_dd_pct: max_dd_pct = dd_pct
        consecutive_losses += 1
        max_consec_losses = max(max_consec_losses, consecutive_losses)
        trades.append({
            "entry_date": today_date, "exit_date": today_date,
            "prev_high": round(prev_high, 1), "entry": round(entry_price, 1),
            "stop": round(stop_price, 1), "target": round(target_price, 1),
            "outcome": outcome, "pnl_r": round(pnl_r, 3),
            "dollar_risk": round(dollar_risk, 2), "dollar_pnl": round(dollar_pnl, 2),
            "equity": round(equity, 2),
        })
        continue

    if float(today["High"]) >= target_price:
        outcome = "win"
        pnl_r = RR_TARGET
        exit_price = target_price
        dollar_pnl = pnl_r * dollar_risk
        equity += dollar_pnl
        equity = max(equity, 0.0)
        if equity > peak_equity: peak_equity = equity
        consecutive_losses = 0
        trades.append({
            "entry_date": today_date, "exit_date": today_date,
            "prev_high": round(prev_high, 1), "entry": round(entry_price, 1),
            "stop": round(stop_price, 1), "target": round(target_price, 1),
            "outcome": outcome, "pnl_r": round(pnl_r, 3),
            "dollar_risk": round(dollar_risk, 2), "dollar_pnl": round(dollar_pnl, 2),
            "equity": round(equity, 2),
        })
        continue

    # Open trade, carry to next days
    in_trade = True
    trade_entry = entry_price
    trade_stop = stop_price
    trade_target = target_price
    trade_risk_pts = risk_pts
    trade_entry_date = today_date
    trade_dollar_risk = dollar_risk
    days_in_trade = 0

# ── Results ───────────────────────────────────────────────────────────────────
results_df = pd.DataFrame(trades)

if results_df.empty:
    print("No trades found.")
else:
    wins   = results_df[results_df["pnl_r"] > 0]
    losses = results_df[results_df["pnl_r"] <= 0]
    total  = len(results_df)

    final_equity = results_df.iloc[-1]["equity"]
    total_pnl    = final_equity - START_CAPITAL
    pct_return   = total_pnl / START_CAPITAL * 100

    results_df["year"]  = results_df["entry_date"].str[:4]
    results_df["month"] = results_df["entry_date"].str[:7]

    yearly  = results_df.groupby("year")["dollar_pnl"].sum().round(2)
    monthly = results_df.groupby("month")["dollar_pnl"].sum().round(2)

    monthly_series = results_df.groupby("month")["dollar_pnl"].sum()
    sharpe = (monthly_series.mean() / monthly_series.std() * (12**0.5)
              if monthly_series.std() > 0 else 0)
    pf_num = results_df[results_df["dollar_pnl"] > 0]["dollar_pnl"].sum()
    pf_den = abs(results_df[results_df["dollar_pnl"] < 0]["dollar_pnl"].sum())
    profit_factor = pf_num / pf_den if pf_den > 0 else 0

    # ── Print report ─────────────────────────────────────────────────────────
    report_lines = [
        "=" * 60,
        f"  10-YEAR BACKTEST: {TICKER} - Daily Bars",
        f"  {df.index[0].date()} to {df.index[-1].date()}",
        "=" * 60,
        f"  Starting capital:  GBP {START_CAPITAL:>10,.2f}",
        f"  Final equity:      GBP {final_equity:>10,.2f}",
        f"  Total profit:      GBP {total_pnl:>10,.2f}  ({pct_return:+.1f}%)",
        f"  CAGR (approx):     {((final_equity/START_CAPITAL)**(1/TARGET_YEARS)-1)*100:.1f}% per year",
        f"",
        f"  Max drawdown:      GBP {max_dd_abs:>10,.2f}  ({max_dd_pct:.1f}%)",
        f"  Max consec losses: {max_consec_losses}",
        f"",
        f"  Total trades:      {total}",
        f"  Win rate:          {len(wins)/total*100:.1f}%",
        f"  Avg R/trade:       {results_df['pnl_r'].mean():+.3f}R",
        f"  Total R:           {results_df['pnl_r'].sum():+.2f}R",
        f"  Best trade:        GBP {results_df['dollar_pnl'].max():,.2f}",
        f"  Worst trade:       GBP {results_df['dollar_pnl'].min():,.2f}",
        f"",
        f"  Annualised Sharpe: {sharpe:.2f}",
        f"  Profit factor:     {profit_factor:.2f}",
        f"  Return / MaxDD:    {pct_return / max_dd_pct:.2f}x",
        "",
        "  Yearly P/L:",
    ]
    for yr, pnl in yearly.items():
        bar = ("+" * min(int(abs(pnl) / (START_CAPITAL * 0.01)), 30)) if pnl > 0 else ("-" * min(int(abs(pnl) / (START_CAPITAL * 0.01)), 30))
        report_lines.append(f"    {yr}  GBP {pnl:>+9.2f}  {bar}")

    report_lines += [
        "",
        "  Equity milestones (every 10 trades):",
    ]
    cumr = results_df["equity"].tolist()
    for idx in range(0, len(cumr), 10):
        report_lines.append(f"    trade {idx+1:>3}: GBP {cumr[idx]:>9,.2f}")
    report_lines.append(f"    trade {len(cumr):>3}: GBP {cumr[-1]:>9,.2f}  (final)")
    report_lines.append("=" * 60)

    for line in report_lines:
        print(line)

    # ── Save files ────────────────────────────────────────────────────────────
    report_path = os.path.join(SAVE_DIR, "backtest_10yr_report.txt")
    trades_path = os.path.join(SAVE_DIR, "backtest_10yr_trades.csv")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    results_df.to_csv(trades_path, index=False)

    print(f"\nSaved:")
    print(f"  {report_path}")
    print(f"  {trades_path}")
