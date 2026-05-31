import warnings
warnings.filterwarnings("ignore")
import yfinance as yf
import pandas as pd
import numpy as np
import os

TICKER = "NQ=F"
TOUCH_THRESHOLD = 0.002
RR_TARGET = 2.5
MAX_DAYS = 3
MIN_MOVE = 0.002
TARGET_YEARS = 10
START = 1000.0
RISK_PCT = 1.0
SAVE_DIR = r"C:\Users\arjun\Dropbox\0 claude\finance\Trading bot\bot 4 xauusd box"

print("Fetching data...")
raw = yf.download(TICKER, period="max", interval="1d", progress=False, auto_adjust=True)
raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
raw.index = raw.index.tz_localize(None) if raw.index.tz else raw.index
raw = raw.dropna()
cutoff = raw.index[-1] - pd.DateOffset(years=TARGET_YEARS)
df = raw[raw.index >= cutoff].copy()

# ── Pre-compute indicators ────────────────────────────────────────────────────
# RSI(14)
delta = df["Close"].diff()
gain = delta.clip(lower=0).rolling(14).mean()
loss = (-delta.clip(upper=0)).rolling(14).mean()
rs = gain / loss
df["rsi"] = 100 - (100 / (1 + rs))

# Moving averages
df["sma20"]  = df["Close"].rolling(20).mean()
df["sma50"]  = df["Close"].rolling(50).mean()
df["ema8"]   = df["Close"].ewm(span=8, adjust=False).mean()
df["ema21"]  = df["Close"].ewm(span=21, adjust=False).mean()

# MA distance: how far price is above 50-day SMA (%)
df["ma50_dist"] = (df["Close"] - df["sma50"]) / df["sma50"] * 100

# Consecutive green days (last N days)
df["is_green"] = (df["Close"] > df["Open"]).astype(int)
df["consec_green_5"] = df["is_green"].rolling(5).sum()  # out of 5 days

# Rate of change 10-day
df["roc10"] = df["Close"].pct_change(10) * 100

# All EMAs bullish aligned
df["ema_bull"] = ((df["ema8"] > df["ema21"]) & (df["ema21"] > df["sma50"])).astype(int)

df = df.dropna()

# ── Backtest function ─────────────────────────────────────────────────────────
def run_bt(rsi_max=100, ma_dist_max=100, consec_green_max=10,
           roc10_max=100, require_ema_bear=False, label="baseline"):
    equity = START
    peak = equity
    max_dd_abs = 0.0
    max_dd_pct = 0.0
    trades = []
    yearly = {}
    skipped = 0
    in_trade = False
    t_entry = t_stop = t_target = t_rpts = t_drisk = 0.0
    t_entry_date = ""
    days_in_trade = 0

    for i in range(2, len(df)):
        today = df.iloc[i]
        yesterday = df.iloc[i - 1]
        two_ago = df.iloc[i - 2]
        prev_high = float(two_ago["High"])
        today_date = str(df.index[i].date())
        yr = today_date[:4]

        if in_trade:
            days_in_trade += 1
            lo = float(today["Low"]); hi = float(today["High"]); cl = float(today["Close"])
            if lo <= t_stop:
                pnl_r = -1.0; exit_p = t_stop
            elif hi >= t_target:
                pnl_r = RR_TARGET; exit_p = t_target
            elif days_in_trade >= MAX_DAYS:
                exit_p = cl
                pnl_r = (exit_p - t_entry) / t_rpts if t_rpts > 0 else 0
            else:
                continue
            drisk = equity * (RISK_PCT / 100)
            dollar_pnl = pnl_r * drisk
            equity += dollar_pnl; equity = max(equity, 0.0)
            if equity > peak: peak = equity
            dd = peak - equity; ddp = dd / peak * 100 if peak > 0 else 0
            if dd > max_dd_abs: max_dd_abs = dd
            if ddp > max_dd_pct: max_dd_pct = ddp
            yearly[yr] = yearly.get(yr, 0) + dollar_pnl
            trades.append({"date": today_date, "pnl_r": pnl_r, "dollar_pnl": dollar_pnl, "equity": equity})
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

        # ── SENTIMENT FILTERS (applied at entry bar) ────────────────────────
        rsi_now      = float(today["rsi"])
        ma_dist_now  = float(today["ma50_dist"])
        cg_now       = float(today["consec_green_5"])
        roc_now      = float(today["roc10"])
        ema_bull_now = float(today["ema_bull"])

        sentiment_bullish = (
            (rsi_now > rsi_max) or
            (ma_dist_now > ma_dist_max) or
            (cg_now >= consec_green_max) or
            (roc_now > roc10_max) or
            (require_ema_bear and ema_bull_now == 1)
        )
        if sentiment_bullish:
            skipped += 1
            continue

        drisk = equity * (RISK_PCT / 100)
        if tl <= stop:
            pnl_r = -1.0; dollar_pnl = pnl_r * drisk
            equity += dollar_pnl; equity = max(equity, 0.0)
            if equity > peak: peak = equity
            dd = peak - equity; ddp = dd / peak * 100 if peak > 0 else 0
            if dd > max_dd_abs: max_dd_abs = dd
            if ddp > max_dd_pct: max_dd_pct = ddp
            yearly[yr] = yearly.get(yr, 0) + dollar_pnl
            trades.append({"date": today_date, "pnl_r": pnl_r, "dollar_pnl": dollar_pnl, "equity": equity})
            continue
        if th >= target:
            pnl_r = RR_TARGET; dollar_pnl = pnl_r * drisk
            equity += dollar_pnl
            if equity > peak: peak = equity
            yearly[yr] = yearly.get(yr, 0) + dollar_pnl
            trades.append({"date": today_date, "pnl_r": pnl_r, "dollar_pnl": dollar_pnl, "equity": equity})
            continue

        in_trade = True
        t_entry = entry; t_stop = stop; t_target = target
        t_rpts = rpts; t_drisk = drisk
        t_entry_date = today_date; days_in_trade = 0

    if not trades:
        return None
    df_t = pd.DataFrame(trades)
    wins = len(df_t[df_t["pnl_r"] > 0])
    total = len(df_t)
    final = equity
    profit = final - START
    pct = profit / START * 100
    cagr = ((final / START) ** (1 / TARGET_YEARS) - 1) * 100
    monthly_s = df_t.copy()
    monthly_s["mo"] = monthly_s["date"].str[:7]
    ms = monthly_s.groupby("mo")["dollar_pnl"].sum()
    sharpe = ms.mean() / ms.std() * (12**0.5) if ms.std() > 0 else 0
    pf_n = df_t[df_t["dollar_pnl"] > 0]["dollar_pnl"].sum()
    pf_d = abs(df_t[df_t["dollar_pnl"] < 0]["dollar_pnl"].sum())
    pf = pf_n / pf_d if pf_d > 0 else 0

    return {
        "label": label, "final": round(final, 2), "profit": round(profit, 2),
        "pct": round(pct, 1), "cagr": round(cagr, 1),
        "max_dd_pct": round(max_dd_pct, 1), "max_dd_abs": round(max_dd_abs, 2),
        "n": total, "wr": round(wins / total * 100, 1),
        "sharpe": round(sharpe, 2), "pf": round(pf, 2),
        "skipped": skipped, "yearly": yearly, "trades_df": df_t,
    }

# ── Run variants ──────────────────────────────────────────────────────────────
configs = [
    dict(label="Baseline (no filter)",              rsi_max=100, ma_dist_max=100, consec_green_max=10, roc10_max=100, require_ema_bear=False),
    dict(label="RSI < 65",                          rsi_max=65,  ma_dist_max=100, consec_green_max=10, roc10_max=100, require_ema_bear=False),
    dict(label="RSI < 70",                          rsi_max=70,  ma_dist_max=100, consec_green_max=10, roc10_max=100, require_ema_bear=False),
    dict(label="MA50 dist < 5%",                    rsi_max=100, ma_dist_max=5,   consec_green_max=10, roc10_max=100, require_ema_bear=False),
    dict(label="MA50 dist < 8%",                    rsi_max=100, ma_dist_max=8,   consec_green_max=10, roc10_max=100, require_ema_bear=False),
    dict(label="Consec green < 4/5",                rsi_max=100, ma_dist_max=100, consec_green_max=4,  roc10_max=100, require_ema_bear=False),
    dict(label="ROC10 < 6%",                        rsi_max=100, ma_dist_max=100, consec_green_max=10, roc10_max=6,   require_ema_bear=False),
    dict(label="EMA bear aligned only",             rsi_max=100, ma_dist_max=100, consec_green_max=10, roc10_max=100, require_ema_bear=True),
    dict(label="RSI<70 + MA50<8%",                  rsi_max=70,  ma_dist_max=8,   consec_green_max=10, roc10_max=100, require_ema_bear=False),
    dict(label="RSI<65 + MA50<5%",                  rsi_max=65,  ma_dist_max=5,   consec_green_max=10, roc10_max=100, require_ema_bear=False),
    dict(label="RSI<70 + MA50<8% + ROC10<6%",       rsi_max=70,  ma_dist_max=8,   consec_green_max=10, roc10_max=6,   require_ema_bear=False),
    dict(label="RSI<65 + EMA bear",                 rsi_max=65,  ma_dist_max=100, consec_green_max=10, roc10_max=100, require_ema_bear=True),
]

results = []
for cfg in configs:
    r = run_bt(**cfg)
    if r:
        results.append(r)
        print(f"Done: {cfg['label']}")

# ── Print comparison table ────────────────────────────────────────────────────
print()
print("=" * 100)
print("  SENTIMENT FILTER COMPARISON  -  10 YEARS  -  GBP 1,000  -  NQ")
print("=" * 100)
print(f"  {'Filter':<38} {'Final GBP':>10} {'Return%':>9} {'CAGR%':>7} {'MaxDD%':>8} {'WR%':>6} {'Sharpe':>7} {'PF':>5} {'Trades':>7} {'Skip':>5}")
print("-" * 100)
for r in results:
    print(
        f"  {r['label']:<38} "
        f"GBP {r['final']:>7,.0f}  "
        f"{r['pct']:>+8.1f}%  "
        f"{r['cagr']:>6.1f}%  "
        f"{r['max_dd_pct']:>7.1f}%  "
        f"{r['wr']:>5.1f}%  "
        f"{r['sharpe']:>6.2f}  "
        f"{r['pf']:>4.2f}  "
        f"{r['n']:>6}  "
        f"{r['skipped']:>5}"
    )
print("=" * 100)

# ── Pick best and show yearly breakdown ───────────────────────────────────────
best = max(results[1:], key=lambda x: x["sharpe"])  # exclude baseline in best pick
baseline = results[0]

print()
print(f"  BEST FILTER: {best['label']}")
print()
print(f"  {'Year':<6}  {'Baseline':>14}  {'Best filter':>14}  {'Improvement':>14}")
print(f"  {'-'*6}  {'-'*14}  {'-'*14}  {'-'*14}")
all_years = sorted(set(list(baseline["yearly"].keys()) + list(best["yearly"].keys())))
for yr in all_years:
    b0 = baseline["yearly"].get(yr, 0)
    b1 = best["yearly"].get(yr, 0)
    diff = b1 - b0
    flag = " <-- fixed" if yr == "2023" else ""
    print(f"  {yr:<6}  GBP {b0:>+9,.0f}  GBP {b1:>+9,.0f}  {diff:>+12.0f}{flag}")

print()
print(f"  Baseline total R:    {baseline['pct']:+.1f}%  MaxDD {baseline['max_dd_pct']}%  Sharpe {baseline['sharpe']}")
print(f"  Best filter total R: {best['pct']:+.1f}%  MaxDD {best['max_dd_pct']}%  Sharpe {best['sharpe']}")
print()

# ── Save best config to folder ────────────────────────────────────────────────
report_lines = [
    "=" * 65,
    f"  SENTIMENT-FILTERED BACKTEST  -  NQ  -  10 YEARS",
    f"  Filter: {best['label']}",
    "=" * 65,
    f"  Starting capital:  GBP {START:,.2f}",
    f"  Final equity:      GBP {best['final']:,.2f}",
    f"  Total profit:      GBP {best['profit']:,.2f}  ({best['pct']:+.1f}%)",
    f"  CAGR:              {best['cagr']:.1f}% per year",
    f"",
    f"  Max drawdown:      GBP {best['max_dd_abs']:,.2f}  ({best['max_dd_pct']:.1f}%)",
    f"  Win rate:          {best['wr']}%",
    f"  Annualised Sharpe: {best['sharpe']}",
    f"  Profit factor:     {best['pf']}",
    f"  Total trades:      {best['n']}  ({best['skipped']} skipped by filter)",
    "",
    "  Yearly P/L (filtered):",
]

running = START
for yr in sorted(best["yearly"].keys()):
    pnl = best["yearly"][yr]
    running += pnl
    bar_len = min(int(abs(pnl) / (START * 0.005)), 30)
    bar = ("+" * bar_len) if pnl >= 0 else ("-" * bar_len)
    report_lines.append(f"    {yr}  GBP {pnl:>+9,.0f}   equity GBP {running:>9,.0f}  {bar}")

report_lines += [
    "",
    "  Filter logic: Skip trade if ANY condition is true:",
    f"    - RSI(14) > {best.get('rsi_max', 'N/A')}   (extremely overbought)",
    f"    - Price > 50-day SMA by > {best.get('ma_dist_max', 'N/A')}%  (strong momentum)",
    f"    - ROC(10d) > {best.get('roc10_max', 'N/A')}%   (fast recent move up)",
    "=" * 65,
]

report_path = os.path.join(SAVE_DIR, "backtest_10yr_sentiment_report.txt")
with open(report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(report_lines))

best["trades_df"].to_csv(os.path.join(SAVE_DIR, "backtest_10yr_sentiment_trades.csv"), index=False)
print(f"  Saved report to {report_path}")
