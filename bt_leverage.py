import warnings
warnings.filterwarnings("ignore")
import yfinance as yf
import pandas as pd
import numpy as np

TICKER = "NQ=F"
TOUCH_THRESHOLD = 0.002
RR_TARGET = 2.5
MAX_DAYS = 3
MIN_MOVE = 0.002
TARGET_YEARS = 10
START = 1000.0

print("Fetching data...")
raw = yf.download(TICKER, period="max", interval="1d", progress=False, auto_adjust=True)
raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
raw.index = raw.index.tz_localize(None) if raw.index.tz else raw.index
raw = raw.dropna()
cutoff = raw.index[-1] - pd.DateOffset(years=TARGET_YEARS)
df = raw[raw.index >= cutoff].copy()


def run(risk_pct):
    equity = START
    peak = equity
    max_dd_abs = 0.0
    max_dd_pct = 0.0
    trades = []
    in_trade = False
    t_entry = t_stop = t_target = t_rpts = t_drisk = 0.0
    days_in_trade = 0
    consec = 0
    max_consec = 0
    blown = False

    for i in range(2, len(df)):
        if equity < 10:
            blown = True
            break

        today = df.iloc[i]
        yesterday = df.iloc[i - 1]
        two_ago = df.iloc[i - 2]
        prev_high = float(two_ago["High"])

        if in_trade:
            days_in_trade += 1
            lo = float(today["Low"])
            hi = float(today["High"])
            cl = float(today["Close"])

            if lo <= t_stop:
                pnl_r = -1.0
                exit_p = t_stop
            elif hi >= t_target:
                pnl_r = RR_TARGET
                exit_p = t_target
            elif days_in_trade >= MAX_DAYS:
                exit_p = cl
                pnl_r = (exit_p - t_entry) / t_rpts if t_rpts > 0 else 0
            else:
                continue

            dollar_pnl = pnl_r * t_drisk
            equity += dollar_pnl
            equity = max(equity, 0.0)
            if equity > peak:
                peak = equity
            dd = peak - equity
            ddp = dd / peak * 100 if peak > 0 else 0
            if dd > max_dd_abs:
                max_dd_abs = dd
            if ddp > max_dd_pct:
                max_dd_pct = ddp
            if pnl_r < 0:
                consec += 1
                max_consec = max(max_consec, consec)
            else:
                consec = 0
            trades.append({"pnl_r": pnl_r, "dollar_pnl": dollar_pnl, "equity": equity})
            in_trade = False
            days_in_trade = 0
            continue

        yh = float(yesterday["High"])
        yl = float(yesterday["Low"])
        yc = float(yesterday["Close"])
        yo = float(yesterday["Open"])

        if not (yh >= prev_high * (1 - TOUCH_THRESHOLD)
                and yc < prev_high
                and prev_high >= yo * (1 + MIN_MOVE)):
            continue

        to = float(today["Open"])
        tc = float(today["Close"])
        tl = float(today["Low"])
        th = float(today["High"])

        if tc <= to:
            continue

        entry = to
        stop = yl
        rpts = entry - stop
        if rpts <= 0 or rpts > entry * 0.025:
            continue

        target = entry + rpts * RR_TARGET
        drisk = min(equity * (risk_pct / 100), equity * 0.99)

        if tl <= stop:
            pnl_r = -1.0
            dollar_pnl = pnl_r * drisk
            equity += dollar_pnl
            equity = max(equity, 0.0)
            if equity > peak:
                peak = equity
            dd = peak - equity
            ddp = dd / peak * 100 if peak > 0 else 0
            if dd > max_dd_abs:
                max_dd_abs = dd
            if ddp > max_dd_pct:
                max_dd_pct = ddp
            consec += 1
            max_consec = max(max_consec, consec)
            trades.append({"pnl_r": pnl_r, "dollar_pnl": dollar_pnl, "equity": equity})
            continue

        if th >= target:
            pnl_r = RR_TARGET
            dollar_pnl = pnl_r * drisk
            equity += dollar_pnl
            if equity > peak:
                peak = equity
            consec = 0
            trades.append({"pnl_r": pnl_r, "dollar_pnl": dollar_pnl, "equity": equity})
            continue

        in_trade = True
        t_entry = entry
        t_stop = stop
        t_target = target
        t_rpts = rpts
        t_drisk = drisk
        days_in_trade = 0

    return {
        "final": round(equity, 2),
        "profit": round(equity - START, 2),
        "pct": round((equity - START) / START * 100, 1),
        "max_dd_abs": round(max_dd_abs, 2),
        "max_dd_pct": round(max_dd_pct, 1),
        "max_consec": max_consec,
        "n": len(trades),
        "blown": blown,
    }


print()
print("LEVERAGE COMPARISON  —  GBP 1,000 start, 10 years, NQ")
print("=" * 72)
print(f"{'Lev':>5}  {'Final GBP':>11}  {'Profit':>11}  {'Return':>8}  {'MaxDD%':>7}  {'MaxDD GBP':>10}  {'Blown':>6}")
print("-" * 72)

for lev in [1, 2, 5, 10, 20]:
    risk_pct = float(lev)
    r = run(risk_pct)
    blown_str = "** BLOWN **" if r["blown"] else "No"
    print(
        f"{str(lev)+'x':>5}  "
        f"GBP {r['final']:>8,.0f}  "
        f"GBP {r['profit']:>+8,.0f}  "
        f"{r['pct']:>+7.1f}%  "
        f"{r['max_dd_pct']:>6.1f}%  "
        f"GBP {r['max_dd_abs']:>7,.0f}  "
        f"{blown_str}"
    )
print("=" * 72)
print()
print("--- 10x leverage detailed yearly breakdown ---")
risk_pct = 10.0
equity = START
yearly_pnl = {}
in_trade = False
t_entry = t_stop = t_target = t_rpts = t_drisk = 0.0
days_in_trade = 0

for i in range(2, len(df)):
    if equity < 10:
        break

    today = df.iloc[i]
    yesterday = df.iloc[i - 1]
    two_ago = df.iloc[i - 2]
    prev_high = float(two_ago["High"])
    yr = str(df.index[i].year)

    if in_trade:
        days_in_trade += 1
        lo = float(today["Low"])
        hi = float(today["High"])
        cl = float(today["Close"])
        if lo <= t_stop:
            pnl_r = -1.0; exit_p = t_stop
        elif hi >= t_target:
            pnl_r = RR_TARGET; exit_p = t_target
        elif days_in_trade >= MAX_DAYS:
            exit_p = cl; pnl_r = (exit_p - t_entry) / t_rpts if t_rpts > 0 else 0
        else:
            continue
        dollar_pnl = pnl_r * t_drisk
        equity += dollar_pnl; equity = max(equity, 0.0)
        yearly_pnl[yr] = yearly_pnl.get(yr, 0) + dollar_pnl
        in_trade = False; days_in_trade = 0
        continue

    yh = float(yesterday["High"]); yl = float(yesterday["Low"])
    yc = float(yesterday["Close"]); yo = float(yesterday["Open"])
    if not (yh >= prev_high * (1 - TOUCH_THRESHOLD) and yc < prev_high and prev_high >= yo * (1 + MIN_MOVE)):
        continue
    to = float(today["Open"]); tc = float(today["Close"])
    tl = float(today["Low"]); th = float(today["High"])
    if tc <= to: continue
    entry = to; stop = yl; rpts = entry - stop
    if rpts <= 0 or rpts > entry * 0.025: continue
    target = entry + rpts * RR_TARGET
    drisk = min(equity * (risk_pct / 100), equity * 0.99)

    if tl <= stop:
        dollar_pnl = -1.0 * drisk; equity += dollar_pnl; equity = max(equity, 0.0)
        yearly_pnl[yr] = yearly_pnl.get(yr, 0) + dollar_pnl; continue
    if th >= target:
        dollar_pnl = RR_TARGET * drisk; equity += dollar_pnl
        yearly_pnl[yr] = yearly_pnl.get(yr, 0) + dollar_pnl; continue

    in_trade = True; t_entry = entry; t_stop = stop; t_target = target
    t_rpts = rpts; t_drisk = drisk; days_in_trade = 0

running = START
for yr in sorted(yearly_pnl.keys()):
    pnl = yearly_pnl[yr]
    running += pnl
    bar = "+" * min(int(abs(pnl) / 50), 30) if pnl > 0 else "-" * min(int(abs(pnl) / 50), 30)
    print(f"  {yr}  GBP {pnl:>+9.2f}  equity: GBP {running:>9,.2f}  {bar}")

print(f"\nFinal: GBP {equity:,.2f}")
