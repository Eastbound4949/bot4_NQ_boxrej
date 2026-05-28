import yfinance as yf
import pandas as pd
from datetime import datetime, date


def _normalize(df: pd.DataFrame, tz: str = "America/New_York") -> pd.DataFrame:
    if df.index.tz is not None:
        df.index = df.index.tz_convert(tz).tz_localize(None)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


def fetch_daily(ticker: str = "NQ=F", days: int = 10) -> pd.DataFrame:
    df = yf.download(ticker, period=f"{days}d", interval="1d", progress=False, auto_adjust=True)
    return _normalize(df)


def fetch_hourly(ticker: str = "NQ=F", days: int = 7) -> pd.DataFrame:
    df = yf.download(ticker, period=f"{days}d", interval="1h", progress=False, auto_adjust=True)
    return _normalize(df)


def fetch_historical(ticker: str = "NQ=F", period: str = "2y"):
    daily  = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
    hourly = yf.download(ticker, period=period, interval="1h", progress=False, auto_adjust=True)
    return _normalize(daily), _normalize(hourly)


def get_prev_day_high(daily_df: pd.DataFrame, today: datetime = None) -> float | None:
    today_date = (today or datetime.now()).date()
    past = daily_df[daily_df.index.date < today_date]
    if past.empty:
        return None
    return float(past.iloc[-1]["High"])


def get_session_bars(hourly_df: pd.DataFrame, session_date: date,
                     start: str = "09:00", end: str = "16:30") -> pd.DataFrame:
    bars = hourly_df[hourly_df.index.date == session_date]
    if bars.empty:
        return bars
    return bars.between_time(start, end)


def get_latest_price(ticker: str = "NQ=F") -> float | None:
    try:
        df = yf.download(ticker, period="1d", interval="1m", progress=False, auto_adjust=True)
        df = _normalize(df)
        return float(df.iloc[-1]["Close"]) if not df.empty else None
    except Exception:
        return None
