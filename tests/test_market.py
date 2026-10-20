import numpy as np
import pandas as pd

from efie.market.calendar import cl_last_trade_date, product_last_trade_date, roll_trading_dates
from efie.market.rolls import consistent_log_returns, consistent_price_change, roll_calendar, roll_flags
from efie.market.sessions import daily_bar_close_utc, hourly_trading_date, session_close_utc, trading_date_from_daily_t


def test_cl_last_trade_dates_match_cme_rule():
    # May 2020 WTI expired on 21 April 2020 (the negative-price contract).
    assert cl_last_trade_date(2020, 5) == pd.Timestamp("2020-04-21")
    # 25 Oct 2026 is a Sunday → anchor Fri 23 Oct → three business days earlier.
    assert cl_last_trade_date(2026, 11) == pd.Timestamp("2026-10-20")
    assert cl_last_trade_date(2026, 10) == pd.Timestamp("2026-09-22")
    # 25 Dec is a holiday and 24 Dec a business day: anchor 24 Dec → 19 Dec 2025.
    assert cl_last_trade_date(2026, 1) == pd.Timestamp("2025-12-19")


def test_product_last_trade_is_last_business_day():
    assert product_last_trade_date(2026, 11) == pd.Timestamp("2026-10-30")
    assert product_last_trade_date(2026, 6) == pd.Timestamp("2026-05-29")


def test_roll_trading_dates_monthly():
    d = roll_trading_dates("2026-01-01", "2026-12-31")
    assert len(d) == 12


def test_session_conventions():
    # Sunday 22:00 UTC daily bar (18:00 EDT) belongs to Monday's session.
    assert trading_date_from_daily_t(pd.Timestamp("2026-10-18 22:00", tz="UTC")) == pd.Timestamp("2026-10-19")
    # ICE Brent daily bar stamped 00:00 UTC stays on its own date.
    assert trading_date_from_daily_t(pd.Timestamp("2026-10-16 00:00", tz="UTC")) == pd.Timestamp("2026-10-16")
    assert session_close_utc("2026-07-01") == pd.Timestamp("2026-07-01 21:00", tz="UTC")  # EDT
    assert session_close_utc("2026-12-01") == pd.Timestamp("2026-12-01 22:00", tz="UTC")  # EST
    assert daily_bar_close_utc(pd.Timestamp("2026-10-18 22:00", tz="UTC")) == pd.Timestamp("2026-10-19 21:00", tz="UTC")
    idx = pd.DatetimeIndex(["2026-10-19 20:00", "2026-10-19 22:00"], tz="UTC")
    assert list(hourly_trading_date(idx)) == [pd.Timestamp("2026-10-19"), pd.Timestamp("2026-10-20")]


def test_roll_reconstruction_finds_synthetic_rolls(synthetic):
    md, true_rolls = synthetic
    found = set(pd.DatetimeIndex(md.roll_h.loc[md.roll_h["method"] == "detected", "roll_index"]))
    in_span = [t for t in true_rolls if md.hourly["CL1"].index[0] < t < md.hourly["CL1"].index[-1]]
    assert in_span and set(in_span) <= found


def test_consistent_returns_remove_roll_jump():
    idx = pd.date_range("2026-01-01", periods=5, freq="1h", tz="UTC")
    front = pd.Series([70.0, 70.1, 69.6, 69.7, 69.8], index=idx)  # rolls at bar 2 (new contract 0.6 lower)
    second = pd.Series([69.4, 69.5, 69.0, 69.1, 69.2], index=idx)
    rolls = pd.Series([False, False, True, False, False], index=idx)
    r = consistent_log_returns(front, second, rolls)
    assert np.isclose(r.iloc[2], np.log(69.6 / 69.5))
    d = consistent_price_change(front, second, rolls)
    assert np.isclose(d.iloc[2], 0.1)


def test_roll_flags():
    idx = pd.date_range("2026-01-01", periods=3, freq="1D")
    cal = pd.DataFrame({"roll_index": [idx[1]]})
    assert roll_flags(idx, cal).tolist() == [False, True, False]


def test_roll_calendar_defaults_when_spread_too_narrow():
    idx = pd.bdate_range("2026-03-01", "2026-04-30")
    rng = np.random.default_rng(1)
    f = pd.Series(70 + np.cumsum(rng.normal(0, 1.0, len(idx))), index=idx)
    s = f - 0.01  # spread far below the noise: undetectable
    cal = roll_calendar(f, s, hourly=False, front_open=f.shift(1).fillna(f))
    assert (cal["method"] == "calendar_default").all()
    assert (cal["offset_bd"] == -2).all()
