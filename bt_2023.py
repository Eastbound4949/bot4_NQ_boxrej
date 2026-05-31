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
RISK_PCT = 1.0  # 1x base, show raw R, scale later

print("Fetching data...")
raw = yf.download(TICKER, period="max", interval="1d", progress=False, auto_adjust=True)
raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
raw.index = raw.index.tz_localize(None) if raw.index.tz else raw.index
raw = raw.dropna()
cutoff = raw.index[-1] - pd.DateOffset(years=TARGET_YEARS)
df = raw[raw.index >= cutoff].copy()

equity = START
trades = []
in_trade = False
t_entry = t_stop = t_target = t_rpts = t_drisk = 0.0
t_entry_date = t_signal_date = ""
days_in_trade = 0

for i in range(2, len(df)):
    today = df.iloc[i]
    yesterday = df.iloc[i - 1]
    two_ago = df.iloc[i - 2]
    prev_high = float(two_ago["High"])
    today_date = str(df.index[i].date())

    if in_trade:
        days_in_trade += 1
        lo = float(today["Low"]); hi = float(today["High"]); cl = float(today["Close"])
        if lo <= t_stop:
            pnl_r = -1.0; exit_p = t_stop; outcome = "LOSS"
        elif hi >= t_target:
            pnl_r = RR_TARGET; exit_p = t_target; outcome = "WIN"
        elif days_in_trade >= MAX_DAYS:
            exit_p = cl; pnl_r = (exit_p - t_entry) / t_rpts if t_rpts > 0 else 0
            outcome = f"TIMEOUT ({pnl_r:+.2f}R)"
        else:
            continue
        drisk = equity * (RISK_PCT / 100)
        dollar_pnl = pnl_r * drisk
        equity += dollar_pnl; equity = max(equity, 0.0)
        trades.append({
            "entry_date": t_entry_date,
            "exit_date": today_date,
            "prev_high": round(prev_high, 1),
            "entry": round(t_entry, 1),
            "stop": round(t_stop, 1),
            "target": round(t_target, 1),
            "exit_price": round(exit_p, 1),
            "risk_pts": round(t_rpts, 1),
            "outcome": outcome,
            "pnl_r": round(pnl_r, 3),
            "nq_price": round(float(today["Close"]), 1),
        })
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
    drisk = equity * (RISK_PCT / 100)

    if tl <= stop:
        dollar_pnl = -1.0 * drisk; equity += dollar_pnl; equity = max(equity, 0.0)
        trades.append({
            "entry_date": today_date, "exit_date": today_date,
            "prev_high": round(prev_high, 1), "entry": round(entry, 1),
            "stop": round(stop, 1), "target": round(target, 1),
            "exit_price": round(stop, 1), "risk_pts": round(rpts, 1),
            "outcome": "LOSS (same day)", "pnl_r": -1.0,
            "nq_price": round(float(today["Close"]), 1),
        })
        continue
    if th >= target:
        dollar_pnl = RR_TARGET * drisk; equity += dollar_pnl
        trades.append({
            "entry_date": today_date, "exit_date": today_date,
            "prev_high": round(prev_high, 1), "entry": round(entry, 1),
            "stop": round(stop, 1), "target": round(target, 1),
            "exit_price": round(target, 1), "risk_pts": round(rpts, 1),
            "outcome": "WIN (same day)", "pnl_r": RR_TARGET,
            "nq_price": round(float(today["Close"]), 1),
        })
        continue

    in_trade = True
    t_entry = entry; t_stop = stop; t_target = target
    t_rpts = rpts; t_drisk = drisk
    t_entry_date = today_date; days_in_trade = 0

df_all = pd.DataFrame(trades)
df_2023 = df_all[df_all["entry_date"].str.startswith("2023")].copy()

print()
print("=" * 90)
print("  ALL TRADES IN 2023 — NQ PREV-DAY-HIGH BOUNCE (1x, shows pure R)")
print("=" * 90)
print(f"  {'#':<4} {'Entry':>12} {'Exit':>12} {'PrevHigh':>10} {'Entry':>10} {'Stop':>10} {'Target':>10} {'Exit@':>10} {'Result':<22} {'R':>6}")
print("-" * 90)

cumr = 0
for idx, row in df_2023.iterrows():
    n = list(df_2023.index).index(idx) + 1
    cumr += row["pnl_r"]
    win_flag = "WIN" if row["pnl_r"] > 0 else "LOSS"
    print(
        f"  {n:<4} {row['entry_date']:>12} {row['exit_date']:>12} "
        f"{row['prev_high']:>10,.0f} {row['entry']:>10,.0f} {row['stop']:>10,.0f} "
        f"{row['target']:>10,.0f} {row['exit_price']:>10,.0f} "
        f"{row['outcome']:<22} {row['pnl_r']:>+6.2f}R"
    )

print("-" * 90)
wins_2023 = df_2023[df_2023["pnl_r"] > 0]
losses_2023 = df_2023[df_2023["pnl_r"] <= 0]
total_r_2023 = df_2023["pnl_r"].sum()
print(f"  2023 TOTAL: {len(df_2023)} trades | {len(wins_2023)} wins / {len(losses_2023)} losses | WR {len(wins_2023)/len(df_2023)*100:.0f}% | Total R: {total_r_2023:+.2f}R")
print()

# Monthly 2023 breakdown
print("  Monthly breakdown:")
df_2023["month"] = df_2023["entry_date"].str[:7]
monthly = df_2023.groupby("month").agg(
    trades=("pnl_r", "count"),
    wins=("pnl_r", lambda x: (x > 0).sum()),
    total_r=("pnl_r", "sum")
).round(2)
for mo, row in monthly.iterrows():
    bar = "+" * int(row["total_r"] * 2) if row["total_r"] > 0 else "-" * int(abs(row["total_r"]) * 2)
    print(f"    {mo}  trades={int(row['trades'])}  wins={int(row['wins'])}  R={row['total_r']:+.2f}  {bar}")

print()
print("  WHY 2023 WAS BAD:")
print()

# Compare 2022 and 2024 stats
for yr in ["2022", "2023", "2024"]:
    dfy = df_all[df_all["entry_date"].str.startswith(yr)]
    if dfy.empty: continue
    wr = len(dfy[dfy["pnl_r"] > 0]) / len(dfy) * 100
    avg_r = dfy["pnl_r"].mean()
    total = dfy["pnl_r"].sum()
    print(f"  {yr}: {len(dfy)} trades | WR {wr:.0f}% | avg {avg_r:+.3f}R | total {total:+.2f}R")

print()
print("  NQ price context (daily close range each year):")
for yr in ["2022", "2023", "2024"]:
    yr_data = df[df.index.year == int(yr)]
    if yr_data.empty: continue
    print(f"  {yr}: NQ ranged {yr_data['Low'].min():.0f} - {yr_data['High'].max():.0f}  |  start {yr_data.iloc[0]['Open']:.0f}  end {yr_data.iloc[-1]['Close']:.0f}  |  trend: {'+' if yr_data.iloc[-1]['Close'] > yr_data.iloc[0]['Open'] else '-'}{abs(yr_data.iloc[-1]['Close']-yr_data.iloc[0]['Open'])/yr_data.iloc[0]['Open']*100:.1f}%")
print("=" * 90)
