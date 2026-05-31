import yfinance as yf
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

daily = yf.download("GC=F", period="2y", interval="1d", progress=False, auto_adjust=True)
hourly = yf.download("GC=F", period="2y", interval="1h", progress=False, auto_adjust=True)
daily.columns = [c[0] if isinstance(c, tuple) else c for c in daily.columns]
hourly.columns = [c[0] if isinstance(c, tuple) else c for c in hourly.columns]
daily.index = daily.index.tz_localize(None) if daily.index.tz is None else daily.index.tz_convert("America/New_York").tz_localize(None)
hourly.index = hourly.index.tz_convert("America/New_York").tz_localize(None) if hourly.index.tz is not None else hourly.index


def run_bt(TOUCH_THRESHOLD=0.003, RR_TARGET=2.0, MAX_BARS=8, MIN_MOVE=0.002):
    trades = []
    trading_days = daily.index[1:]
    for i, day in enumerate(trading_days):
        prev_day = daily.index[i]
        prev_high = float(daily.loc[prev_day, "High"])
        day_bars = hourly[hourly.index.date == day.date()]
        if len(day_bars) > 0:
            day_bars = day_bars.between_time("06:00", "18:00")
        if len(day_bars) < 3:
            continue
        session_open = float(day_bars.iloc[0]["Open"])
        if prev_high < session_open * (1 + MIN_MOVE):
            continue
        in_rejection = False
        signal_fired = False
        for j in range(len(day_bars) - 1):
            bar = day_bars.iloc[j]
            close = float(bar["Close"])
            high = float(bar["High"])
            low = float(bar["Low"])
            open_ = float(bar["Open"])
            if not in_rejection and not signal_fired:
                if high >= prev_high * (1 - TOUCH_THRESHOLD) and close < prev_high:
                    in_rejection = True
                    continue
            if in_rejection and not signal_fired:
                is_green = close > open_
                if is_green and j + 1 < len(day_bars):
                    entry_bar = day_bars.iloc[j + 1]
                    entry_price = float(entry_bar["Open"])
                    stop_price = low
                    risk = entry_price - stop_price
                    if risk <= 0 or risk > entry_price * 0.025:
                        in_rejection = False
                        continue
                    target_price = entry_price + (risk * RR_TARGET)
                    signal_fired = True
                    pnl_r = 0
                    outcome = "open"
                    for k in range(j + 1, min(j + 1 + MAX_BARS, len(day_bars))):
                        fut = day_bars.iloc[k]
                        if float(fut["Low"]) <= stop_price:
                            outcome = "loss"
                            pnl_r = -1.0
                            break
                        if float(fut["High"]) >= target_price:
                            outcome = "win"
                            pnl_r = RR_TARGET
                            break
                    else:
                        exit_price = float(day_bars.iloc[min(j + 1 + MAX_BARS, len(day_bars) - 1)]["Close"])
                        pnl_r = (exit_price - entry_price) / risk if risk > 0 else 0
                        outcome = "timeout"
                    trades.append({"pnl_r": pnl_r, "outcome": outcome})
                    break
    if not trades:
        return None
    df_t = pd.DataFrame(trades)
    wins = len(df_t[df_t["pnl_r"] > 0])
    total = len(df_t)
    wr = wins / total * 100
    total_r = df_t["pnl_r"].sum()
    peak = 0
    running = 0
    max_dd = 0
    for r in df_t["pnl_r"]:
        running += r
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)
    return {"n": total, "wr": round(wr, 1), "total_r": round(total_r, 2), "max_dd": round(max_dd, 2)}


print(f"{'RR':<5} {'Touch%':<8} {'N':<5} {'WR%':<8} {'Total_R':<10} {'MaxDD':<8}")
best = None
for rr in [1.0, 1.5, 2.0, 2.5, 3.0]:
    for touch in [0.002, 0.003, 0.005]:
        r = run_bt(RR_TARGET=rr, TOUCH_THRESHOLD=touch)
        if r:
            print(f"{rr:<5.1f} {touch*100:<7.1f}% {r['n']:<5} {r['wr']:<7.1f}% {r['total_r']:<10.2f} {r['max_dd']:<8.2f}")
            if best is None or r["total_r"] > best[2]:
                best = (rr, touch, r["total_r"], r)

print()
if best:
    print(f"Best combo: RR={best[0]}, Touch={best[1]*100:.1f}%, Total_R={best[2]:.2f}")
    print(f"Details: {best[3]}")
