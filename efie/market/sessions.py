"""CME Globex session conventions.

A CME energy session runs 18:00 ET to 17:00 ET the next day; the session is named
after the day it ends on (the "trading date"). TradingView stamps a daily bar with
the session's open time (22:00 or 23:00 UTC the evening before), and an hourly bar
with its own open time.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")
SESSION_CLOSE = time(17, 0)


def trading_date_from_daily_t(t: pd.Timestamp) -> pd.Timestamp:
    """Trading date of a daily bar stamped at its session open (UTC).

    Futures daily bars open between 20:00 and 01:00 UTC; four hours later is always
    inside the session's own trading date.
    """
    return pd.Timestamp((t.tz_convert("UTC") + timedelta(hours=4)).date())


def session_close_utc(trading_date) -> pd.Timestamp:
    d = pd.Timestamp(trading_date).date()
    return pd.Timestamp(datetime.combine(d, SESSION_CLOSE, tzinfo=ET)).tz_convert("UTC")


def daily_bar_close_utc(t: pd.Timestamp) -> pd.Timestamp:
    return session_close_utc(trading_date_from_daily_t(t))


def hourly_trading_date(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Trading date of each hourly bar (by its open time)."""
    et = index.tz_convert(ET)
    # Bars opening at or after 18:00 ET belong to the next day's session.
    shifted = et + pd.Timedelta(hours=6)
    return pd.DatetimeIndex(shifted.date.astype("datetime64[ns]"))


def first_bar_of_session(index: pd.DatetimeIndex) -> np.ndarray:
    td = hourly_trading_date(index)
    first = np.ones(len(index), dtype=bool)
    first[1:] = td[1:] != td[:-1]
    return first


def last_bar_of_session(index: pd.DatetimeIndex) -> np.ndarray:
    td = hourly_trading_date(index)
    last = np.ones(len(index), dtype=bool)
    last[:-1] = td[:-1] != td[1:]
    return last


def first_session_of_month(trading_dates: pd.DatetimeIndex) -> np.ndarray:
    """True for the first trading date of each calendar month (per row)."""
    td = pd.DatetimeIndex(trading_dates)
    month = td.year * 12 + td.month
    out = np.ones(len(td), dtype=bool)
    out[1:] = month[1:] != month[:-1]
    return out
