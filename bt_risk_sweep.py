"""
Risk % sweep — find best CAGR under 20% max DD constraint.
Tests risk_pct 0.5% to 15% in 0.5% steps.

Run: python bt_risk_sweep.py
"""

import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
import numpy as np
import os

# ── Fixed strategy params (optimised) ────────────────────────────────────────
TICKER          = "NQ=F"
TOUCH_THRESHOLD = 0.005
RR_TARGET       = 3.5
MAX_DAYS        = 2
MIN_MOVE        = 0.002
START_CAPITAL   = 1000.0
TARGET_YEARS    = 10
DD_LIMIT        = 20.0   # hard cap

SAVE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Fetch once ────────────────────────────────────────────────────────────────
print("Fetching NQ=F daily data...")
raw = yf.download(TICKER, period="max", interval="1d", progress=False, auto_adjust=True)
raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
raw.index = raw.index.tz_localize(None) if raw.index.tz else raw.index
raw = raw.dropna()
cutoff = raw.index[-1] - pd.DateOffset(years=TARGET_YEARS)
df = raw[raw.index >= cutoff].copy()
print(f"Using {len(df)} days: {df.index[0].date()} to {df.index[-1].date()}\n")


def run_backtest(risk_pct: float) -> dict:
    equity = START_CAPITAL
    peak_equity = equity
    max_dd_pct = 0.0
    max_dd_abs = 0.0
    trades = []
    consec_losses = 0
    max_consec = 0
    in_trade = False
    trade_entry = trade_stop = trade_target = trade_risk_pts = 0.0
    trade_dollar_risk = 0.0
    days_in_trade = 0
    trade_entry_date = ""

    for i in range(2, len(df)):
        today     = df.iloc[i]
        yesterday = df.iloc[i - 1]
        two_ago   = df.iloc[i - 2]
        prev_high = float(two_ago["High"])
        today_date = str(df.index[i].date())

        if in_trade:
            days_in_trade += 1
            lo = float(today["Low"])
            hi = float(today["High"])
            close = float(today["Close"])

            if lo <= trade_stop:
                outcome, pnl_r, exit_price = "loss", -1.0, trade_stop
            elif hi >= trade_target:
                outcome, pnl_r, exit_price = "win", RR_TARGET, trade_target
            elif days_in_trade >= MAX_DAYS:
                exit_price = close
                pnl_r = (exit_price - trade_entry) / trade_risk_pts if trade_risk_pts > 0 else 0
                outcome = "timeout"
            else:
                continue

            dollar_pnl = pnl_r * trade_dollar_risk
            equity += dollar_pnl
            equity = max(equity, 0.0)
            if equity > peak_equity: peak_equity = equity
            dd_pct = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
            dd_abs = peak_equity - equity
            if dd_pct > max_dd_pct: max_dd_pct = dd_pct
            if dd_abs > max_dd_abs: max_dd_abs = dd_abs
            if pnl_r < 0:
                consec_losses += 1
                max_consec = max(max_consec, consec_losses)
            else:
                consec_losses = 0
            trades.append({"entry_date": trade_entry_date, "dollar_pnl": dollar_pnl, "pnl_r": pnl_r, "equity": equity})
            in_trade = False
            days_in_trade = 0
            continue

        yest_high  = float(yesterday["High"])
        yest_low   = float(yesterday["Low"])
        yest_close = float(yesterday["Close"])
        yest_open  = float(yesterday["Open"])
        touched   = yest_high >= prev_high * (1 - TOUCH_THRESHOLD)
        rejected  = yest_close < prev_high
        min_level = prev_high >= yest_open * (1 + MIN_MOVE)
        if not (touched and rejected and min_level): continue

        today_open  = float(today["Open"])
        today_close = float(today["Close"])
        if not (today_close > today_open): continue

        entry_price = today_open
        stop_price  = yest_low
        risk_pts    = entry_price - stop_price
        if risk_pts <= 0 or risk_pts > entry_price * 0.025: continue

        target_price = entry_price + (risk_pts * RR_TARGET)
        dollar_risk  = equity * (risk_pct / 100)

        def record(outcome, pnl_r):
            nonlocal equity, peak_equity, max_dd_pct, max_dd_abs, consec_losses, max_consec
            dp = pnl_r * dollar_risk
            equity += dp
            equity = max(equity, 0.0)
            if equity > peak_equity: peak_equity = equity
            dp2 = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
            da2 = peak_equity - equity
            if dp2 > max_dd_pct: max_dd_pct = dp2
            if da2 > max_dd_abs: max_dd_abs = da2
            if pnl_r < 0:
                consec_losses += 1
                max_consec = max(max_consec, consec_losses)
            else:
                consec_losses = 0
            trades.append({"entry_date": today_date, "dollar_pnl": dp, "pnl_r": pnl_r, "equity": equity})

        if float(today["Low"]) <= stop_price:
            record("loss", -1.0)
            continue
        if float(today["High"]) >= target_price:
            record("win", RR_TARGET)
            continue

        in_trade = True
        trade_entry = entry_price
        trade_stop  = stop_price
        trade_target = target_price
        trade_risk_pts = risk_pts
        trade_entry_date = today_date
        trade_dollar_risk = dollar_risk
        days_in_trade = 0

    if not trades:
        return {"risk_pct": risk_pct, "cagr": 0, "max_dd": 0, "sharpe": 0, "trades": 0, "wr": 0}

    tdf = pd.DataFrame(trades)
    final_eq = tdf.iloc[-1]["equity"]
    total_ret = (final_eq / START_CAPITAL - 1) * 100
    cagr = ((final_eq / START_CAPITAL) ** (1 / TARGET_YEARS) - 1) * 100
    tdf["month"] = tdf["entry_date"].str[:7]
    ms = tdf.groupby("month")["dollar_pnl"].sum()
    sharpe = ms.mean() / ms.std() * (12 ** 0.5) if ms.std() > 0 else 0
    wins = (tdf["pnl_r"] > 0).sum()
    wr = wins / len(tdf) * 100
    pf_n = tdf[tdf["dollar_pnl"] > 0]["dollar_pnl"].sum()
    pf_d = abs(tdf[tdf["dollar_pnl"] < 0]["dollar_pnl"].sum())
    pf = pf_n / pf_d if pf_d > 0 else 0

    return {
        "risk_pct": risk_pct,
        "cagr": round(cagr, 1),
        "total_ret": round(total_ret, 1),
        "final_eq": round(final_eq, 2),
        "max_dd": round(max_dd_pct, 1),
        "sharpe": round(sharpe, 2),
        "trades": len(tdf),
        "wr": round(wr, 1),
        "profit_factor": round(pf, 2),
        "max_consec_losses": max_consec,
    }


# ── Sweep ─────────────────────────────────────────────────────────────────────
risk_levels = [round(x * 0.5, 1) for x in range(2, 31)]  # 1.0% to 15.0%
results = []

print(f"{'Risk%':>6}  {'CAGR%':>7}  {'MaxDD%':>7}  {'Sharpe':>7}  {'PF':>5}  {'WR%':>5}  {'TotalRet%':>10}  {'OK':>4}")
print("-" * 70)

for r in risk_levels:
    res = run_backtest(r)
    ok = "YES" if res["max_dd"] < DD_LIMIT else "---"
    print(f"  {res['risk_pct']:>4.1f}  {res['cagr']:>7.1f}  {res['max_dd']:>7.1f}  {res['sharpe']:>7.2f}  {res['profit_factor']:>5.2f}  {res['wr']:>5.1f}  {res['total_ret']:>10.1f}  {ok:>4}")
    results.append(res)

# ── Best under DD limit ───────────────────────────────────────────────────────
valid = [r for r in results if r["max_dd"] < DD_LIMIT]
best = max(valid, key=lambda x: x["cagr"]) if valid else None

print("\n" + "=" * 70)
if best:
    print(f"  BEST UNDER {DD_LIMIT:.0f}% DD:")
    print(f"    Risk %:       {best['risk_pct']}%")
    print(f"    CAGR:         {best['cagr']}%/yr")
    print(f"    Max DD:       {best['max_dd']}%")
    print(f"    Sharpe:       {best['sharpe']}")
    print(f"    Profit Factor:{best['profit_factor']}")
    print(f"    Win Rate:     {best['wr']}%")
    print(f"    Total Return: +{best['total_ret']}%  (£{best['final_eq']:,.2f} from £1,000)")
    print(f"    Trades:       {best['trades']}  ({best['trades']//TARGET_YEARS}/yr)")
else:
    print("  No risk level passes DD filter.")
print("=" * 70)

# ── Save CSV ──────────────────────────────────────────────────────────────────
out = pd.DataFrame(results)
out.to_csv(os.path.join(SAVE_DIR, "bt_risk_sweep_results.csv"), index=False)
print(f"\nSaved: bt_risk_sweep_results.csv")
