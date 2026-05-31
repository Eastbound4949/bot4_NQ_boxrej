import warnings
warnings.filterwarnings("ignore")
import yfinance as yf
import pandas as pd

TICKER = "NQ=F"
TOUCH_THRESHOLD = 0.002
RR_TARGET = 2.5
MAX_DAYS = 3
MIN_MOVE = 0.002
TARGET_YEARS = 10
START = 1000.0
RISK_PCT = 5.0  # 5x leverage = 5% per trade

print("Fetching data...")
raw = yf.download(TICKER, period="max", interval="1d", progress=False, auto_adjust=True)
raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
raw.index = raw.index.tz_localize(None) if raw.index.tz else raw.index
raw = raw.dropna()
cutoff = raw.index[-1] - pd.DateOffset(years=TARGET_YEARS)
df = raw[raw.index >= cutoff].copy()

equity = START
peak = equity
max_dd_abs = 0.0
max_dd_pct = 0.0
worst_dd_period = ("", "", 0.0)
trades = []
yearly_pnl = {}
monthly_pnl = {}
in_trade = False
t_entry = t_stop = t_target = t_rpts = t_drisk = 0.0
days_in_trade = 0
consec = 0
max_consec = 0
peak_date = ""
trough_equity = equity

for i in range(2, len(df)):
    if equity < 10:
        print("ACCOUNT BLOWN")
        break

    today = df.iloc[i]
    yesterday = df.iloc[i - 1]
    two_ago = df.iloc[i - 2]
    prev_high = float(two_ago["High"])
    today_date = str(df.index[i].date())
    yr = today_date[:4]
    mo = today_date[:7]

    if in_trade:
        days_in_trade += 1
        lo = float(today["Low"]); hi = float(today["High"]); cl = float(today["Close"])
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
        if equity > peak:
            peak = equity; peak_date = today_date
        dd = peak - equity; ddp = dd / peak * 100 if peak > 0 else 0
        if dd > max_dd_abs:
            max_dd_abs = dd; max_dd_pct = ddp
        if pnl_r < 0:
            consec += 1; max_consec = max(max_consec, consec)
        else:
            consec = 0
        yearly_pnl[yr] = yearly_pnl.get(yr, 0) + dollar_pnl
        monthly_pnl[mo] = monthly_pnl.get(mo, 0) + dollar_pnl
        trades.append({"date": today_date, "pnl_r": pnl_r, "dollar_pnl": dollar_pnl, "equity": equity, "outcome": "win" if pnl_r > 0 else ("loss" if pnl_r == -1 else "timeout")})
        in_trade = False; days_in_trade = 0
        continue

    yh = float(yesterday["High"]); yl = float(yesterday["Low"])
    yc = float(yesterday["Close"]); yo = float(yesterday["Open"])
    if not (yh >= prev_high * (1 - TOUCH_THRESHOLD) and yc < prev_high and prev_high >= yo * (1 + MIN_MOVE)):
        continue

    to = float(today["Open"]); tc = float(today["Close"])
    tl = float(today["Low"]); th = float(today["High"])
    if tc <= to:
        continue

    entry = to; stop = yl; rpts = entry - stop
    if rpts <= 0 or rpts > entry * 0.025:
        continue

    target = entry + rpts * RR_TARGET
    drisk = min(equity * (RISK_PCT / 100), equity * 0.99)

    if tl <= stop:
        pnl_r = -1.0; dollar_pnl = pnl_r * drisk
        equity += dollar_pnl; equity = max(equity, 0.0)
        if equity > peak: peak = equity; peak_date = today_date
        dd = peak - equity; ddp = dd / peak * 100 if peak > 0 else 0
        if dd > max_dd_abs: max_dd_abs = dd; max_dd_pct = ddp
        consec += 1; max_consec = max(max_consec, consec)
        yearly_pnl[yr] = yearly_pnl.get(yr, 0) + dollar_pnl
        monthly_pnl[mo] = monthly_pnl.get(mo, 0) + dollar_pnl
        trades.append({"date": today_date, "pnl_r": pnl_r, "dollar_pnl": dollar_pnl, "equity": equity, "outcome": "loss"})
        continue

    if th >= target:
        pnl_r = RR_TARGET; dollar_pnl = pnl_r * drisk
        equity += dollar_pnl
        if equity > peak: peak = equity; peak_date = today_date
        consec = 0
        yearly_pnl[yr] = yearly_pnl.get(yr, 0) + dollar_pnl
        monthly_pnl[mo] = monthly_pnl.get(mo, 0) + dollar_pnl
        trades.append({"date": today_date, "pnl_r": pnl_r, "dollar_pnl": dollar_pnl, "equity": equity, "outcome": "win"})
        continue

    in_trade = True
    t_entry = entry; t_stop = stop; t_target = target
    t_rpts = rpts; t_drisk = drisk; days_in_trade = 0

df_trades = pd.DataFrame(trades)
wins = df_trades[df_trades["pnl_r"] > 0]
losses = df_trades[df_trades["pnl_r"] == -1.0]
total = len(df_trades)
final = equity
profit = final - START
pct_ret = profit / START * 100
cagr = ((final / START) ** (1 / TARGET_YEARS) - 1) * 100
pf_n = df_trades[df_trades["dollar_pnl"] > 0]["dollar_pnl"].sum()
pf_d = abs(df_trades[df_trades["dollar_pnl"] < 0]["dollar_pnl"].sum())
pf = pf_n / pf_d if pf_d > 0 else 0
monthly_s = pd.Series(monthly_pnl)
sharpe = monthly_s.mean() / monthly_s.std() * (12**0.5) if monthly_s.std() > 0 else 0

print()
print("=" * 62)
print("  5x LEVERAGE BACKTEST  -  GBP 1,000  -  10 YEARS  -  NQ")
print("=" * 62)
print(f"  Starting capital:   GBP {START:>11,.2f}")
print(f"  Final equity:       GBP {final:>11,.2f}")
print(f"  Total profit:       GBP {profit:>11,.2f}  ({pct_ret:+.1f}%)")
print(f"  CAGR:               {cagr:.1f}% per year")
print()
print(f"  Max drawdown:       GBP {max_dd_abs:>11,.2f}  ({max_dd_pct:.1f}%)")
print(f"  Max consec losses:  {max_consec}")
print()
print(f"  Total trades:       {total}")
print(f"  Win rate:           {len(wins)/total*100:.1f}%")
print(f"  Avg R/trade:        {df_trades['pnl_r'].mean():+.3f}R")
print(f"  Profit factor:      {pf:.2f}")
print(f"  Annualised Sharpe:  {sharpe:.2f}")
print(f"  Return / MaxDD:     {pct_ret / max_dd_pct:.1f}x")
print(f"  Best trade:         GBP {df_trades['dollar_pnl'].max():>11,.2f}")
print(f"  Worst trade:        GBP {df_trades['dollar_pnl'].min():>11,.2f}")
print()
print("  Yearly P/L:")
running = START
for yr in sorted(yearly_pnl.keys()):
    pnl = yearly_pnl[yr]
    running += pnl
    sign = "+" if pnl >= 0 else ""
    bar_len = min(int(abs(pnl) / (START * 0.02)), 28)
    bar = ("+" * bar_len) if pnl >= 0 else ("-" * bar_len)
    print(f"    {yr}  GBP {pnl:>+11,.2f}   equity GBP {running:>10,.2f}  {bar}")

print()
print("  Worst drawdown months (any month > -5%):")
monthly_pct = {m: v / (running - sum(list(monthly_pnl.values())[i:])) * 100
               for i, (m, v) in enumerate(sorted(monthly_pnl.items()))
               if v < 0}
bad_months = {m: v for m, v in sorted(monthly_pnl.items()) if v < -START * 0.05}
if bad_months:
    for m, v in sorted(bad_months.items(), key=lambda x: x[1]):
        print(f"    {m}:  GBP {v:>+10,.2f}")
else:
    print("    None exceeding -5% of starting capital")

print("=" * 62)
print()
print("  VERDICT:")
if max_dd_pct < 40:
    verdict = "Survivable. Most CFD brokers allow 50%+ drawdown before margin call."
    action = "5x leverage is viable IF you can stomach seeing -36% temporarily."
else:
    verdict = "DANGER ZONE. Drawdown approaches margin call territory."
    action = "Margin call risk is real at this leverage level."
print(f"  {verdict}")
print(f"  {action}")
print("=" * 62)
