"""
Dukascopy tick-data downloader for NQ (USTEC / US Tech 100 CFD).
Downloads bi5 hourly tick files, parses them, resamples to any OHLCV timeframe.

Usage:
    from dukascopy_feed import fetch_dukascopy
    df_30m = fetch_dukascopy("USTEC", days=730, resample="30min")
    df_15m = fetch_dukascopy("USTEC", days=730, resample="15min")

Instrument codes to try: USTEC  /  NAS100USD  /  USATEC
"""

import struct, lzma, time, os
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# NQ/USTEC price factor: raw bi5 int32 / PRICE_FACTOR = actual price
# Dukascopy stores USTEC with 2 decimal places → factor = 100
# (auto-detected on first successful download)
_PRICE_FACTOR = None

SESSION_HOURS = list(range(9, 17))   # 09:00–16:00 ET (hours to download)
TZ_NY = timezone(timedelta(hours=-4))  # approximate ET (no DST handling; data will be filtered)

BASE_URL = "https://datafeed.dukascopy.com/datafeed"


def _download_bi5(instrument: str, year: int, month0: int, day: int, hour: int,
                  session: requests.Session, retries: int = 2) -> bytes | None:
    """Download one hourly tick file (month0 = 0-based month)."""
    url = f"{BASE_URL}/{instrument}/{year}/{month0:02d}/{day:02d}/{hour:02d}h_ticks.bi5"
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 200 and len(r.content) > 10:
                return r.content
        except Exception:
            if attempt < retries:
                time.sleep(1)
    return None


def _parse_bi5(raw_bytes: bytes, year: int, month: int, day: int, hour: int) -> list[dict]:
    """Decompress LZMA bi5 and parse ticks → list of {ts, ask, bid} dicts."""
    global _PRICE_FACTOR
    try:
        data = lzma.decompress(raw_bytes)
    except lzma.LZMAError:
        return []

    base_dt = datetime(year, month, day, hour, tzinfo=timezone.utc)
    ticks = []
    for i in range(0, len(data) - 19, 20):
        chunk = data[i: i + 20]
        ms_off, ask_raw, bid_raw, _, _ = struct.unpack(">5i", chunk)
        if ms_off < 0 or ms_off > 3_600_000:
            continue
        ts = base_dt + timedelta(milliseconds=ms_off)

        # Auto-detect price factor on first valid tick
        if _PRICE_FACTOR is None:
            for factor in (100, 10, 1000, 1):
                price = ask_raw / factor
                if 10_000 < price < 30_000:   # NQ range
                    _PRICE_FACTOR = factor
                    break
            if _PRICE_FACTOR is None:
                return []

        ask = ask_raw / _PRICE_FACTOR
        bid = bid_raw / _PRICE_FACTOR
        ticks.append({"ts": ts, "ask": ask, "bid": bid})

    return ticks


def _ticks_to_ohlcv(ticks: list[dict], resample: str) -> pd.DataFrame:
    """Convert flat tick list → resampled OHLCV DataFrame."""
    if not ticks:
        return pd.DataFrame()
    df = pd.DataFrame(ticks)
    df["mid"] = (df["ask"] + df["bid"]) / 2
    df = df.set_index("ts").sort_index()
    ohlcv = df["mid"].resample(resample).ohlc()
    ohlcv["Volume"] = df["ask"].resample(resample).count()
    ohlcv.columns = ["Open", "High", "Low", "Close", "Volume"]
    return ohlcv.dropna()


def fetch_dukascopy(
    instrument: str = "USTEC",
    days: int = 730,
    resample: str = "30min",
    workers: int = 8,
    cache_dir: str | None = None,
    session_hours: list[int] | None = None,
) -> pd.DataFrame:
    """
    Download Dukascopy tick data and return resampled OHLCV.

    Args:
        instrument  : Dukascopy instrument code (e.g. "USTEC")
        days        : history length in calendar days
        resample    : pandas resample rule ("30min", "15min", "1h", etc.)
        workers     : parallel download threads
        cache_dir   : if set, cache downloaded bi5 files here to avoid re-downloading
        session_hours: list of UTC hours to download (default RTH approx 13–21 UTC = 9–17 ET)
    """
    global _PRICE_FACTOR
    _PRICE_FACTOR = None   # reset for each call

    if session_hours is None:
        # 13:00–20:00 UTC ≈ 09:00–16:00 ET (covers DST shift too)
        session_hours = list(range(13, 21))

    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)

    end_dt   = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=days)

    # Build list of (year, month0, day, hour) tuples
    jobs = []
    cur = start_dt
    while cur < end_dt:
        if cur.weekday() < 5:   # Mon–Fri
            for h in session_hours:
                jobs.append((cur.year, cur.month - 1, cur.day, h))
        cur += timedelta(days=1)

    print(f"  Dukascopy: {instrument}  {len(jobs)} hourly files to fetch "
          f"({start_dt.date()} – {end_dt.date()}) ...")

    session = requests.Session()
    all_ticks: list[dict] = []
    done = 0

    def _fetch_one(args):
        yr, mo0, dy, hr = args
        if cache_dir:
            fname = os.path.join(cache_dir, f"{instrument}_{yr}_{mo0:02d}_{dy:02d}_{hr:02d}.bi5")
            if os.path.exists(fname):
                with open(fname, "rb") as f:
                    raw = f.read()
            else:
                raw = _download_bi5(instrument, yr, mo0, dy, hr, session)
                if raw:
                    with open(fname, "wb") as f:
                        f.write(raw)
        else:
            raw = _download_bi5(instrument, yr, mo0, dy, hr, session)
        return _parse_bi5(raw, yr, mo0 + 1, dy, hr) if raw else []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_one, j): j for j in jobs}
        for fut in as_completed(futures):
            ticks = fut.result()
            all_ticks.extend(ticks)
            done += 1
            if done % 200 == 0:
                pct = done / len(jobs) * 100
                print(f"    {done}/{len(jobs)} ({pct:.0f}%)  ticks so far: {len(all_ticks):,}", end="\r")

    print(f"\n  Total ticks: {len(all_ticks):,}  →  resampling to {resample} ...")

    if not all_ticks:
        print("  ERROR: no ticks received. Try a different instrument code.")
        print("  Common codes to try: USTEC  NAS100USD  USATEC  NQ")
        return pd.DataFrame()

    df = _ticks_to_ohlcv(all_ticks, resample)

    # Convert UTC → New York time (approximate: subtract 4h; good enough for session filtering)
    df.index = df.index.tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)

    print(f"  Bars: {len(df)}  ({df.index[0]} – {df.index[-1]})")
    return df


if __name__ == "__main__":
    print("Testing Dukascopy feed for USTEC (NAS100 CFD)...")
    df = fetch_dukascopy(
        instrument="USTEC",
        days=30,      # small test: last 30 days
        resample="30min",
        workers=6,
        cache_dir=os.path.join(os.path.dirname(__file__), "_duka_cache"),
    )
    if not df.empty:
        print(f"\nSample data:\n{df.tail(10)}")
        print(f"\nPrice range: {df['Low'].min():.0f} – {df['High'].max():.0f}")
    else:
        print("Failed. Try instruments: NAS100USD, USATEC, NQ")
