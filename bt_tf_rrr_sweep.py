"""
NQ Box Rejection — Timeframe × RRR Sweep (2-year backtest)
=============================================================
Sweeps all combinations of:
  Timeframes : daily (2yr), 1h (2yr), 30m (~60d*), 15m (~60d*)
  RR targets : 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0
  Touch %    : 0.1%, 0.2%, 0.3%, 0.5%
  Max bars   : equivalent ~3h / ~5h / ~8h per timeframe

* yfinance free tier: 30m/15m limited to last 60 days only

Signal logic (intraday):
  Rejection bar: high >= prev_day_high*(1-touch), close < prev_day_high
  Confirmation : next green bar (close > open)
  Entry        : bar after confirmation, at open
  Stop         : confirmation bar low
  Target       : entry + risk * RR

Signal logic (daily):
  Rejection bar: yesterday
  Entry day    : today (green), at open
  Stop         : rejection bar (yesterday) low
  Target       : entry + risk * RR

Ranks by Calmar = Return% / MaxDD%
Output: console table + bt_tf_rrr_results.csv
"""
import warnings
warnings.filterwarnings("ignore")

import yfinance as yf
import pandas as pd
from itertools import product
import os, sys

TICKER       = "NQ=F"
RISK_PCT     = 1.0
START_CAP    = 1000.0
SESSION_S    = "09:00"
SESSION_E    = "16:30"
MIN_MOVE     = 0.002   # prev_high must be >= 0.2% above session open
MAX_RISK_BAR = 0.025   # max risk per entry = 2.5% of price (filters huge stops)
MIN_TRADES   = 8
SAVE_DIR     = os.path.dirname(os.path.abspath(__file__))


# ── Data fetch ────────────────────────────────────────────────────────────────

def _fetch(interval, period):
    df = yf.download(TICKER, period=period, interval=interval,
                     progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    if df.index.tz is not None:
        df.index = df.index.tz_convert("America/New_York").tz_localize(None)
    return df.dropna()


# ── Equity tracker ────────────────────────────────────────────────────────────

def _apply_trade(equity, peak, max_dd_pct, pnl_r, dol_risk):
    equity = max(0.0, equity + pnl_r * dol_risk)
    if equity > peak:
        peak = equity
    if peak > 0:
        dd = (peak - equity) / peak * 100
        if dd > max_dd_pct:
            max_dd_pct = dd
    return equity, peak, max_dd_pct


# ── Stats ─────────────────────────────────────────────────────────────────────

def _stats(trades, max_dd_pct, final_equity):
    if len(trades) < MIN_TRADES:
        return None
    df = pd.DataFrame(trades)
    total = len(df)
    wins  = len(df[df["pnl_r"] > 0])
    wr    = wins / total * 100
    tot_r = df["pnl_r"].sum()
    pct   = (final_equity - START_CAP) / START_CAP * 100
    cal   = pct / max_dd_pct if max_dd_pct > 0 else 0.0
    p_win = df[df["pnl_r"] > 0]["pnl_r"].sum()
    p_los = abs(df[df["pnl_r"] <= 0]["pnl_r"].sum())
    pf    = p_win / p_los if p_los > 0 else float("inf")
    return {
        "n": total, "wr": round(wr, 1), "total_r": round(tot_r, 2),
        "pct_ret": round(pct, 1), "max_dd": round(max_dd_pct, 1),
        "calmar": round(cal, 2), "pf": round(min(pf, 99.9), 2),
    }


# ── Daily bar engine ──────────────────────────────────────────────────────────

def bt_daily(rr, touch, max_days):
    df = _daily
    equity, peak, max_dd = START_CAP, START_CAP, 0.0
    in_trade = False
    t_entry = t_stop = t_target = t_risk = t_dol = 0.0
    days_held = 0
    trades = []

    for i in range(2, len(df)):
        today = df.iloc[i]
        yest  = df.iloc[i - 1]
        prev  = df.iloc[i - 2]
        prev_high = float(prev["High"])

        # Manage open trade
        if in_trade:
            days_held += 1
            lo, hi, cl = float(today["Low"]), float(today["High"]), float(today["Close"])
            if lo <= t_stop:
                pnl_r = -1.0
            elif hi >= t_target:
                pnl_r = rr
            elif days_held >= max_days:
                exit_p = cl
                pnl_r  = (exit_p - t_entry) / t_risk if t_risk > 0 else 0.0
            else:
                continue

            equity, peak, max_dd = _apply_trade(equity, peak, max_dd, pnl_r, t_dol)
            trades.append({"pnl_r": pnl_r})
            in_trade  = False
            days_held = 0
            continue

        # Signal: yesterday = rejection
        yh, yl, yc, yo = (float(yest["High"]), float(yest["Low"]),
                          float(yest["Close"]), float(yest["Open"]))
        if not (yh >= prev_high * (1 - touch) and yc < prev_high
                and prev_high >= yo * (1 + MIN_MOVE)):
            continue

        # Entry: today green
        to_, tc_, tl_, th_ = (float(today["Open"]), float(today["Close"]),
                               float(today["Low"]),  float(today["High"]))
        if tc_ <= to_:
            continue

        entry = to_
        stop  = yl             # rejection bar's low (yesterday)
        risk  = entry - stop
        if risk <= 0 or risk > entry * MAX_RISK_BAR:
            continue

        target   = entry + risk * rr
        dol_risk = equity * (RISK_PCT / 100)

        # Intra-day resolution on entry bar
        if tl_ <= stop:
            pnl_r = -1.0
        elif th_ >= target:
            pnl_r = rr
        else:
            in_trade = True
            t_entry, t_stop, t_target = entry, stop, target
            t_risk, t_dol = risk, dol_risk
            days_held = 0
            continue

        equity, peak, max_dd = _apply_trade(equity, peak, max_dd, pnl_r, dol_risk)
        trades.append({"pnl_r": pnl_r})

    return _stats(trades, max_dd, equity)


# ── Intraday bar engine ───────────────────────────────────────────────────────

def bt_intraday(intra_df, rr, touch, max_bars):
    equity, peak, max_dd = START_CAP, START_CAP, 0.0
    trades = []

    # Iterate calendar days using daily reference for prev_high
    trading_days = _daily.index[1:]

    for i, day in enumerate(trading_days):
        prev_high = float(_daily.iloc[i]["High"])  # previous day's high

        day_bars = intra_df[intra_df.index.date == day.date()]
        if not day_bars.empty:
            day_bars = day_bars.between_time(SESSION_S, SESSION_E)
        if len(day_bars) < 3:
            continue

        session_open = float(day_bars.iloc[0]["Open"])
        if prev_high < session_open * (1 + MIN_MOVE):
            continue

        in_rejection = False

        for j in range(len(day_bars) - 1):
            bar = day_bars.iloc[j]
            close = float(bar["Close"])
            high  = float(bar["High"])
            low   = float(bar["Low"])
            open_ = float(bar["Open"])

            if not in_rejection:
                if high >= prev_high * (1 - touch) and close < prev_high:
                    in_rejection = True
                    continue  # move to next bar (potential confirmation)

            if in_rejection:
                if close > open_:  # green = confirmation
                    if j + 1 >= len(day_bars):
                        break
                    next_bar = day_bars.iloc[j + 1]
                    entry = float(next_bar["Open"])
                    stop  = low   # confirmation bar's low
                    risk  = entry - stop
                    if risk <= 0 or risk > entry * MAX_RISK_BAR:
                        in_rejection = False
                        continue

                    target   = entry + risk * rr
                    dol_risk = equity * (RISK_PCT / 100)

                    pnl_r   = 0.0
                    outcome = "timeout"
                    end_k   = min(j + 1 + max_bars, len(day_bars))
                    for k in range(j + 1, end_k):
                        fut = day_bars.iloc[k]
                        if float(fut["Low"]) <= stop:
                            pnl_r, outcome = -1.0, "loss"
                            break
                        if float(fut["High"]) >= target:
                            pnl_r, outcome = rr, "win"
                            break
                    else:
                        last = min(j + max_bars, len(day_bars) - 1)
                        exit_p = float(day_bars.iloc[last]["Close"])
                        pnl_r  = (exit_p - entry) / risk if risk > 0 else 0.0

                    equity, peak, max_dd = _apply_trade(equity, peak, max_dd, pnl_r, dol_risk)
                    trades.append({"pnl_r": pnl_r})
                    break  # one signal per day

    return _stats(trades, max_dd, equity)


# ── Main ──────────────────────────────────────────────────────────────────────

print(f"Fetching {TICKER} data (this may take 30s)...")
_daily  = _fetch("1d", "2y")
_hourly = _fetch("1h", "2y")
_m30    = _fetch("30m", "60d")
_m15    = _fetch("15m", "60d")

print(f"  Daily 2yr:  {len(_daily)} days  "
      f"({_daily.index[0].date()} – {_daily.index[-1].date()})")
print(f"  1h    2yr:  {len(_hourly)} bars")

if not _m30.empty:
    print(f"  30m  ~60d:  {len(_m30)} bars  "
          f"({_m30.index[0].date()} – {_m30.index[-1].date()})")
else:
    print("  30m: no data returned")

if not _m15.empty:
    print(f"  15m  ~60d:  {len(_m15)} bars  "
          f"({_m15.index[0].date()} – {_m15.index[-1].date()})")
else:
    print("  15m: no data returned")

# Parameter grids
RR_VALUES    = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
TOUCH_VALUES = [0.001, 0.002, 0.003, 0.005]

# max_bars chosen so each row ≈ equivalent session time:
#   Daily : 2/3/5 days
#   1h    : 3/5/8 hours  (up to full session ~7h)
#   30m   : 6/10/16 bars (3h / 5h / 8h)
#   15m   : 12/20/32 bars(3h / 5h / 8h)
CONFIGS = [
    ("Daily (2yr)",  "daily",  [2, 3, 5]),
    ("1h    (2yr)",  "1h",     [3, 5, 8]),
    ("30m   (~60d)", "30m",    [6, 10, 16]),
    ("15m   (~60d)", "15m",    [12, 20, 32]),
]

results = []
count   = 0
total   = sum(
    len(RR_VALUES) * len(TOUCH_VALUES) * len(mb)
    for _, _, mb in CONFIGS
)

print(f"\nRunning {total} parameter combinations...")

for tf_name, tf_id, mb_list in CONFIGS:
    for rr, touch, max_bars in product(RR_VALUES, TOUCH_VALUES, mb_list):
        count += 1
        if count % 50 == 0:
            pct_done = count / total * 100
            print(f"  {count}/{total} ({pct_done:.0f}%) ...", end="\r")

        if tf_id == "daily":
            stats = bt_daily(rr, touch, max_bars)
        elif tf_id == "1h":
            stats = bt_intraday(_hourly, rr, touch, max_bars)
        elif tf_id == "30m":
            if _m30.empty:
                continue
            stats = bt_intraday(_m30, rr, touch, max_bars)
        elif tf_id == "15m":
            if _m15.empty:
                continue
            stats = bt_intraday(_m15, rr, touch, max_bars)
        else:
            continue

        if stats:
            results.append({
                "tf":        tf_name,
                "rr":        rr,
                "touch_pct": round(touch * 100, 2),
                "max_bars":  max_bars,
                **stats,
            })

print(f"\n{len(results)} valid combos found (min {MIN_TRADES} trades threshold)\n")

if not results:
    print("No results — check data download.")
    sys.exit(1)

df_res = pd.DataFrame(results).sort_values("calmar", ascending=False)

# Save CSV
csv_path = os.path.join(SAVE_DIR, "bt_tf_rrr_results.csv")
df_res.to_csv(csv_path, index=False)

# ── Print report ──────────────────────────────────────────────────────────────
W = 102
SEP = "=" * W
DIV = "-" * W

HDR = (
    f"{'Timeframe':<16} {'RR':<5} {'Touch%':<8} {'MaxBars':<9} "
    f"{'N':<5} {'WR%':<7} {'TotalR':<9} {'Ret%':<8} {'MaxDD%':<8} "
    f"{'Calmar':<9} PF"
)

def _row(row):
    pf = f"{row['pf']:.2f}" if row["pf"] < 99 else ">99"
    return (
        f"{row['tf']:<16} {row['rr']:<5.1f} {row['touch_pct']:<7.2f}% "
        f"{row['max_bars']:<9} {row['n']:<5} {row['wr']:<7.1f} "
        f"{row['total_r']:<9.2f} {row['pct_ret']:<7.1f}% "
        f"{row['max_dd']:<7.1f}% {row['calmar']:<9.2f} {pf}"
    )

print(SEP)
print(f"  NQ=F  TIMEFRAME × RRR SWEEP — Top 25  (ranked by Calmar = Return% / MaxDD%)")
print(SEP)
print(HDR)
print(DIV)
for _, row in df_res.head(25).iterrows():
    print(_row(row))
print(SEP)

# ── Best by total_R (for absolute return hunters) ─────────────────────────────
print(f"\n  Top 10 by TOTAL_R (absolute R earned)")
print(DIV)
print(HDR)
print(DIV)
for _, row in df_res.sort_values("total_r", ascending=False).head(10).iterrows():
    print(_row(row))
print(DIV)

# ── Best per timeframe ────────────────────────────────────────────────────────
print(f"\n  BEST CONFIG PER TIMEFRAME  (Calmar-ranked)")
print("=" * 80)
for tf_name, _, _ in CONFIGS:
    subset = df_res[df_res["tf"] == tf_name]
    if subset.empty:
        print(f"  {tf_name:<16}  no valid results")
        continue
    b = subset.iloc[0]
    pf = f"{b['pf']:.2f}" if b["pf"] < 99 else ">99"
    print(
        f"  {b['tf']:<16}  RR={b['rr']:.1f}  Touch={b['touch_pct']:.2f}%  "
        f"MaxBars={b['max_bars']}  Calmar={b['calmar']:.2f}  "
        f"Ret={b['pct_ret']:+.1f}%  DD={b['max_dd']:.1f}%  "
        f"WR={b['wr']:.1f}%  Trades={b['n']}  PF={pf}"
    )
print("=" * 80)
print(f"\nFull results: {csv_path}")
print(f"(30m/15m results limited to last ~60 days of data — fewer trades, less reliable)")
