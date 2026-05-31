import yfinance as yf
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")

TICKER = "NQ=F"  # Nasdaq 100 futures

daily = yf.download(TICKER, period="2y", interval="1d", progress=False, auto_adjust=True)
hourly = yf.download(TICKER, period="2y", interval="1h", progress=False, auto_adjust=True)
daily.columns = [c[0] if isinstance(c, tuple) else c for c in daily.columns]
hourly.columns = [c[0] if isinstance(c, tuple) else c for c in hourly.columns]
daily.index = daily.index.tz_localize(None) if daily.index.tz is None else daily.index.tz_convert("America/New_York").tz_localize(None)
hourly.index = hourly.index.tz_convert("America/New_York").tz_localize(None) if hourly.index.tz is not None else hourly.index

print(f"Daily: {len(daily)} rows, {daily.index[0].date()} to {daily.index[-1].date()}")
print(f"Hourly: {len(hourly)} rows")


def run_bt(TOUCH_THRESHOLD=0.002, RR_TARGET=2.0, MAX_BARS=8, MIN_MOVE=0.002):
    trades = []
    trading_days = daily.index[1:]
    for i, day in enumerate(trading_days):
        prev_day = daily.index[i]
        prev_high = float(daily.loc[prev_day, "High"])
        day_bars = hourly[hourly.index.date == day.date()]
        if len(day_bars) > 0:
            day_bars = day_bars.between_time("09:00", "16:30")
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
                    if risk <= 0 or risk > entry_price * 0.02:
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
                    trades.append({
                        "date": str(day.date()),
                        "pnl_r": round(pnl_r, 2),
                        "outcome": outcome,
                        "entry": round(entry_price, 1),
                        "prev_high": round(prev_high, 1),
                        "risk_pts": round(risk, 1),
                    })
                    break
    return pd.DataFrame(trades) if trades else pd.DataFrame()


print("\n--- Full sweep ---")
print(f"{'RR':<5} {'Touch%':<8} {'N':<5} {'WR%':<8} {'Total_R':<10} {'MaxDD':<8}")
best_r = -999
best_params = None
best_df = None

for rr in [1.0, 1.5, 2.0, 2.5]:
    for touch in [0.001, 0.002, 0.003]:
        df_t = run_bt(RR_TARGET=rr, TOUCH_THRESHOLD=touch)
        if df_t.empty:
            continue
        wins = len(df_t[df_t["pnl_r"] > 0])
        total = len(df_t)
        wr = wins / total * 100
        total_r = df_t["pnl_r"].sum()
        peak = 0; running = 0; max_dd = 0
        for r in df_t["pnl_r"]:
            running += r; peak = max(peak, running); max_dd = max(max_dd, peak - running)
        print(f"{rr:<5.1f} {touch*100:<7.2f}% {total:<5} {wr:<7.1f}% {total_r:<10.2f} {max_dd:<8.2f}")
        if total_r > best_r:
            best_r = total_r; best_params = (rr, touch); best_df = df_t.copy()

print()
if best_df is not None:
    print(f"Best: RR={best_params[0]}, Touch={best_params[1]*100:.2f}%, Total_R={best_r:.2f}")
    wins = len(best_df[best_df["pnl_r"] > 0])
    total = len(best_df)
    print(f"Trades={total}, WR={wins/total*100:.1f}%")
    print()
    print("Monthly P/L (best params):")
    best_df["month"] = pd.to_datetime(best_df["date"]).dt.to_period("M")
    monthly = best_df.groupby("month")["pnl_r"].agg(["sum", "count"]).round(2)
    monthly.columns = ["pnl_r", "trades"]
    print(monthly.to_string())
    print()
    print("Outcome breakdown:")
    print(best_df["outcome"].value_counts().to_string())
    print()
    print("Cumulative R curve:")
    cumr = best_df["pnl_r"].cumsum().round(2)
    for idx, val in enumerate(cumr):
        if idx % 5 == 0:
            print(f"  trade {idx+1:>3}: {val:>8.2f}R")
    print(f"  trade {len(cumr):>3}: {cumr.iloc[-1]:>8.2f}R  (final)")
