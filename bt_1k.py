import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, r"C:\Users\arjun\Dropbox\0 claude\finance\Trading bot\bot 4 xauusd box")

from backtest import run_backtest, print_report

stats = run_backtest(ticker="NQ=F", period="2y", risk_pct=1.0, account_size=1000)
print_report(stats)

df = stats["trades_df"]
df["year"] = df["date"].str[:4]

print()
print("=== GBP 1000 ACCOUNT — KEY STATS ===")
print(f"Starting:     GBP 1,000.00")
print(f"Final equity: GBP {stats['final_equity']:,.2f}")
print(f"Total profit: GBP {stats['total_pnl']:,.2f}  ({stats['pct_return']:+.1f}%)")
print(f"Max drawdown: GBP {stats['max_dd_abs']:,.2f}  ({stats['max_dd_pct']:.1f}%)")
print(f"Best trade:   GBP {stats['best_trade']:,.2f}")
print(f"Worst trade:  GBP {stats['worst_trade']:,.2f}")
print(f"Trades:       {stats['total_trades']} over 2 years")
print(f"Win rate:     {stats['win_rate']}%")
print()
print("Year 1 vs Year 2:")
yearly = df.groupby("year")["dollar_pnl"].sum().round(2)
for yr, pnl in yearly.items():
    print(f"  {yr}: GBP {pnl:+,.2f}")

# Sharpe-like ratio
import numpy as np
monthly_pnl = df.copy()
monthly_pnl["month"] = df["date"].str[:7]
monthly_returns = monthly_pnl.groupby("month")["dollar_pnl"].sum()
sharpe = monthly_returns.mean() / monthly_returns.std() * (12**0.5) if monthly_returns.std() > 0 else 0
profit_factor_num = df[df["dollar_pnl"] > 0]["dollar_pnl"].sum()
profit_factor_den = abs(df[df["dollar_pnl"] < 0]["dollar_pnl"].sum())
profit_factor = profit_factor_num / profit_factor_den if profit_factor_den > 0 else 0
print()
print(f"Annualised Sharpe: {sharpe:.2f}")
print(f"Profit factor:     {profit_factor:.2f}")
print(f"Return/MaxDD:      {stats['pct_return'] / stats['max_dd_pct']:.2f}x")
