"""NYMEX contract calendar (known in advance, so roll dates carry no look-ahead).

WTI crude (CL, and MCL's underlying cycle): trading in a contract terminates three
business days before the 25th calendar day of the month before delivery; if the 25th is
not a business day, four business days before the 25th. Equivalently: take the last
business day on or before the 25th, then step back three business days.

RBOB (RB) and ULSD (HO): trading terminates on the last business day of the month before
delivery.

Business days exclude weekends and the CME holidays below. The holiday list is the
standard US exchange set; an occasional ad-hoc closure is not covered, which is why the
calendar is cross-checked against the data in ``efie diagnose``.
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
)
from pandas.tseries.offsets import CustomBusinessDay


class CMEHolidays(AbstractHolidayCalendar):
    rules = [
        Holiday("New Year", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


@lru_cache(maxsize=1)
def business_day() -> CustomBusinessDay:
    return CustomBusinessDay(calendar=CMEHolidays())


def is_business_day(d: pd.Timestamp) -> bool:
    bd = business_day()
    d = pd.Timestamp(d).normalize()
    return bd.is_on_offset(d)


def cl_last_trade_date(delivery_year: int, delivery_month: int) -> pd.Timestamp:
    prev = pd.Timestamp(delivery_year, delivery_month, 1) - pd.offsets.MonthBegin(1)
    d25 = pd.Timestamp(prev.year, prev.month, 25)
    bd = business_day()
    anchor = d25 if is_business_day(d25) else d25 - bd
    return anchor - 3 * bd


def product_last_trade_date(delivery_year: int, delivery_month: int) -> pd.Timestamp:
    first = pd.Timestamp(delivery_year, delivery_month, 1)
    return first - business_day()


def roll_trading_dates(start: str, end: str, product: str = "CL") -> pd.DatetimeIndex:
    """First trading date on which the continuous front month is the next contract."""
    bd = business_day()
    out = []
    for m in pd.period_range(pd.Timestamp(start) - pd.DateOffset(months=1), pd.Timestamp(end) + pd.DateOffset(months=2), freq="M"):
        ltd = cl_last_trade_date(m.year, m.month) if product == "CL" else product_last_trade_date(m.year, m.month)
        out.append(ltd + bd)
    idx = pd.DatetimeIndex(sorted(set(out)))
    return idx[(idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))]
