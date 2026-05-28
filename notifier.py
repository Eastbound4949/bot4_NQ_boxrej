import requests
import logging

log = logging.getLogger(__name__)


def send(token: str, chat_id: str, text: str) -> bool:
    if not token or token.startswith("YOUR_"):
        log.warning("Telegram not configured — skipping notification")
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


def fmt_entry(ticker, entry, stop, target, risk_pts, prev_high, dollar_risk, account):
    rr = (target - entry) / (entry - stop) if entry != stop else 0
    return (
        f"*NQ BOT — ENTRY SIGNAL*\n"
        f"Ticker: `{ticker}`\n"
        f"Prev Day High: `{prev_high:,.1f}`\n"
        f"─────────────────\n"
        f"Entry:  `{entry:,.1f}`\n"
        f"Stop:   `{stop:,.1f}`  (-{risk_pts:.1f} pts)\n"
        f"Target: `{target:,.1f}`  (RR {rr:.1f}:1)\n"
        f"─────────────────\n"
        f"$ Risk: `${dollar_risk:,.2f}`  ({dollar_risk/account*100:.1f}% of account)\n"
        f"Mode: `{'PAPER' if True else 'LIVE'}`"
    )


def fmt_exit(ticker, outcome, entry, exit_price, pnl_r, dollar_pnl, new_balance):
    emoji = "✅" if pnl_r > 0 else ("⏱" if "timeout" in outcome.lower() else "❌")
    return (
        f"{emoji} *NQ BOT — TRADE CLOSED*\n"
        f"Ticker: `{ticker}`\n"
        f"─────────────────\n"
        f"Entry:     `{entry:,.1f}`\n"
        f"Exit:      `{exit_price:,.1f}`\n"
        f"Outcome:   `{outcome.upper()}`\n"
        f"P/L:       `{pnl_r:+.2f}R  =  ${dollar_pnl:+,.2f}`\n"
        f"─────────────────\n"
        f"Balance:   `${new_balance:,.2f}`"
    )


def fmt_daily_summary(ticker, date, trades_today, daily_pnl, balance):
    emoji = "📈" if daily_pnl >= 0 else "📉"
    return (
        f"{emoji} *NQ BOT — Daily Summary* ({date})\n"
        f"Ticker: `{ticker}`\n"
        f"Trades today: `{trades_today}`\n"
        f"Daily P/L:    `${daily_pnl:+,.2f}`\n"
        f"Balance:      `${balance:,.2f}`"
    )


def fmt_startup(ticker, account, paper):
    mode = "PAPER TRADING" if paper else "LIVE TRADING"
    return (
        f"🤖 *NQ BOT STARTED*\n"
        f"Ticker:  `{ticker}`\n"
        f"Mode:    `{mode}`\n"
        f"Account: `${account:,.2f}`\n"
        f"Strategy: Prev Day High Bounce\n"
        f"RR: 2.5:1 | Risk: 1%/trade"
    )
