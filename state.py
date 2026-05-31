"""
Persistent state — survives Railway redeploys via JSON on disk.
"""
import json
import os
from dataclasses import dataclass, asdict

STATE_FILE = os.environ.get("STATE_FILE", "bot_state.json")


@dataclass
class BotState:
    balance: float = 1000.0
    in_trade: bool = False
    entry_price: float = 0.0
    stop_price: float = 0.0
    target_price: float = 0.0
    risk_pts: float = 0.0
    dollar_risk: float = 0.0
    prev_high: float = 0.0
    entry_date: str = ""
    days_in_trade: int = 0          # kept for backwards compat; not used in daily logic
    trades_today: int = 0
    daily_pnl: float = 0.0
    last_session_date: str = ""
    total_trades: int = 0
    total_wins: int = 0
    signal_checked_today: bool = False  # daily signal fires once per session


def load(starting_balance: float = 1000.0) -> BotState:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            # Fill in any new fields that old state files won't have
            for field in ("signal_checked_today",):
                if field not in data:
                    data[field] = False
            return BotState(**data)
        except Exception:
            pass
    return BotState(balance=starting_balance)


def save(state: BotState):
    with open(STATE_FILE, "w") as f:
        json.dump(asdict(state), f, indent=2)
