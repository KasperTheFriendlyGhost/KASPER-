"""Synthetic market fixtures. No real market data is stored in the repository; tests that
need the real snapshot skip themselves when it is absent."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from efie.features.build import MarketData, load_market_data
from efie.market.calendar import business_day, cl_last_trade_date
from efie.market.rolls import roll_calendar
from efie.market.sessions import ET, hourly_trading_date

START = pd.Timestamp("2025-11-02 23:00", tz="UTC")  # a Sunday session open (EST)
DAYS = 120


def _hourly_index() -> pd.DatetimeIndex:
    idx = pd.date_range(START, START + pd.Timedelta(days=DAYS), freq="1h")
    et = idx.tz_convert(ET)
    keep = []
    for t in et:
        wd, h = t.dayofweek, t.hour
        if h == 17:  # daily halt 17:00–18:00 ET
            keep.append(False)
        elif wd == 5 or (wd == 4 and h >= 17) or (wd == 6 and h < 18):
            keep.append(False)
        else:
            keep.append(True)
    idx = idx[np.array(keep)]
    # CME holidays as full-day closures would complicate nothing here; keep weekdays only.
    return idx


def _roll_bars(idx: pd.DatetimeIndex) -> list[int]:
    """Session-open bar of trading date LTD-2 for every contract in range."""
    td = hourly_trading_date(idx)
    bd = business_day()
    out = []
    for m in pd.period_range(td.min(), td.max() + pd.DateOffset(months=2), freq="M"):
        day = cl_last_trade_date(m.year, m.month) - 2 * bd
        pos = np.where(td == day)[0]
        if len(pos) and pos[0] > 0:
            out.append(int(pos[0]))
    return out


@pytest.fixture(scope="session")
def synthetic():
    """(MarketData, true roll bar timestamps)."""
    rng = np.random.default_rng(7)
    idx = _hourly_index()
    n = len(idx)
    base = 70 + np.cumsum(rng.normal(0, 0.15, n))
    rolls = _roll_bars(idx)
    k = np.zeros(n, dtype=int)
    for r in rolls:
        k[r:] += 1
    # Contract j trades at base - 0.6*j (steady backwardation of 0.60 per month).
    cl1 = base - 0.6 * k + rng.normal(0, 0.01, n)
    cl2 = base - 0.6 * (k + 1) + rng.normal(0, 0.01, n)

    # Each bar opens where its own contract closed the bar before; on a roll bar the new
    # front month opens next to the previous second-month close (as in real data).
    base_prev = np.r_[base[0], base[:-1]]
    open1 = base_prev - 0.6 * k + rng.normal(0, 0.01, n)
    open2 = base_prev - 0.6 * (k + 1) + rng.normal(0, 0.01, n)

    def bars(c, o=None):
        o = np.r_[c[0], c[:-1]] if o is None else o
        return pd.DataFrame({"o": o, "h": np.maximum(o, c) + 0.05, "l": np.minimum(o, c) - 0.05, "c": c, "v": rng.integers(100, 1000, n).astype(float)}, index=idx)

    hourly = {
        "CL1": bars(cl1, open1),
        "CL2": bars(cl2, open2),
        "MCL1": bars(cl1 + rng.normal(0, 0.01, n)),
        "RB1": bars((cl1 + 25 + rng.normal(0, 0.3, n)) / 42),
        "HO1": bars((cl1 + 35 + rng.normal(0, 0.3, n)) / 42),
    }
    et = idx.tz_convert(ET)
    etf = (et.dayofweek < 5) & (((et.hour == 9) & (et.minute == 0)) | ((et.hour >= 10) & (et.hour < 16)))
    bw_idx = idx[etf] + pd.Timedelta(minutes=30)
    hourly["BWET"] = pd.DataFrame({"o": 20.0, "h": 20.5, "l": 19.5, "c": 20 + np.cumsum(rng.normal(0, 0.1, len(bw_idx))), "v": 1000.0}, index=bw_idx)

    td = hourly_trading_date(idx)
    def daily(df):
        g = df.groupby(td)
        out = pd.DataFrame({"o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last(), "v": g["v"].sum()})
        out.index = pd.DatetimeIndex(out.index, name="date")
        return out
    dly = {s: daily(hourly[s]) for s in ("CL1", "CL2", "RB1", "HO1")}
    dly["BRN1"] = dly["CL1"].assign(c=dly["CL1"]["c"] + 5)
    dly["TL1"] = dly["CL1"].assign(c=15 + np.cumsum(rng.normal(0, 0.2, len(dly["CL1"]))))

    rows = []
    eid = 0
    for wed in pd.date_range(START.normalize(), START + pd.Timedelta(days=DAYS), freq="W-WED"):
        rel = pd.Timestamp(wed.date()).tz_localize(ET) + pd.Timedelta(hours=10, minutes=30)
        api = rel - pd.Timedelta(hours=18)
        ref = (wed - pd.Timedelta(days=5)).tz_localize("UTC") if wed.tzinfo is None else wed - pd.Timedelta(days=5)
        for series, ts, cons in (
            ("eia_crude", rel, True), ("eia_gasoline", rel, True), ("eia_distillate", rel, True),
            ("eia_cushing", rel, False), ("eia_runs", rel, False), ("eia_imports", rel, False), ("api_crude", api, True),
        ):
            eid += 1
            a = float(rng.normal(0, 3e6))
            rows.append({
                "event_id": str(eid), "series": series, "ticker": series, "title": series,
                "release_ts": ts.tz_convert("UTC"), "reference_date": pd.Timestamp(ref.date()).tz_localize("UTC"), "period": str(ref.date()),
                "actual": a, "consensus": float(a + rng.normal(0, 2e6)) if cons else np.nan, "previous": np.nan,
                "importance": 0, "source": "synthetic",
            })
    events = pd.DataFrame(rows).sort_values(["series", "release_ts"]).reset_index(drop=True)
    events["next_previous"] = np.nan
    events["revision"] = np.nan
    roll_h = roll_calendar(hourly["CL1"]["c"], hourly["CL2"]["c"], hourly=True, front_open=hourly["CL1"]["o"])
    roll_d = roll_calendar(dly["CL1"]["c"], dly["CL2"]["c"], hourly=False, front_open=dly["CL1"]["o"], override=roll_h)
    md = MarketData(hourly, dly, events, roll_h, roll_d, idx[-1] + pd.Timedelta(hours=1))
    return md, [idx[r] for r in rolls]


@pytest.fixture(scope="session")
def synthetic_md(synthetic) -> MarketData:
    return synthetic[0]


@pytest.fixture(scope="session")
def real_md():
    try:
        md = load_market_data()
    except Exception:  # noqa: BLE001
        md = None
    if md is None or md.hourly["CL1"].empty:
        pytest.skip("real data snapshot not staged in data/raw (licensed data is not in git)")
    return md
