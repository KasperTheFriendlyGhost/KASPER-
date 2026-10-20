import numpy as np
import pandas as pd

from efie.backtest import overlays as ov
from efie.backtest.engine import daily_pnl, hourly_pnl, summarize
from efie.backtest.strategies import load_signal_csv
from efie.config import cost_per_side_usd, load_config, round_trip_cost_usd


def _frame(n=6, roll_at=None):
    idx = pd.date_range("2026-03-02 14:00", periods=n, freq="1h", tz="UTC")
    f = pd.DataFrame(index=idx)
    f["tau"] = idx + pd.Timedelta(hours=1)
    f["dP"] = [0.0, 0.10, -0.20, 0.30, 0.05, -0.10][:n]
    f["roll"] = False
    if roll_at is not None:
        f.iloc[roll_at, f.columns.get_loc("roll")] = True
    f["trading_date"] = pd.Timestamp("2026-03-02")
    f["ts_spread12"] = [0.5, 0.5, -0.2, -0.2, 0.5, 0.5][:n]
    return f


def test_costs_from_config():
    cfg = load_config()
    c = cfg["costs"]
    per_side = c["commission_per_side_usd"] + c["slippage_ticks_per_side"] * cfg["instrument"]["tick_value_usd"]
    assert np.isclose(cost_per_side_usd(cfg), per_side)
    assert np.isclose(round_trip_cost_usd(cfg, 2.0), 4 * per_side)


def test_hourly_position_earns_next_bar_only():
    cfg = load_config()
    f = _frame()
    pos = pd.Series([0, 1, 1, 0, 0, 0], index=f.index, dtype=float)
    p = hourly_pnl(f, pos, cfg)
    mult = cfg["instrument"]["multiplier_bbl"]
    # Long decided at bar 1's close earns bars 2 and 3; nothing from bar 1 itself.
    assert np.isclose(p["gross"].sum(), (-0.20 + 0.30) * mult)
    assert np.isclose(p["costs"].sum(), 2 * cost_per_side_usd(cfg))


def test_roll_costs_round_trip():
    cfg = load_config()
    f = _frame(roll_at=3)
    pos = pd.Series([1, 1, 1, 1, 1, 1], index=f.index, dtype=float)
    p = hourly_pnl(f, pos, cfg)
    assert np.isclose(p["costs"].sum(), cost_per_side_usd(cfg) + 2 * cost_per_side_usd(cfg))


def test_daily_fill_at_next_open():
    cfg = load_config()
    idx = pd.bdate_range("2026-03-02", periods=4)
    f = pd.DataFrame(index=idx)
    f["gap_next"] = [0.5, -0.2, 0.1, np.nan]
    f["intraday_next"] = [1.0, 2.0, -1.0, np.nan]
    f["roll"] = False
    pos = pd.Series([1, 1, 0, 0], index=idx, dtype=float)
    p = daily_pnl(f, pos, cfg)
    mult = cfg["instrument"]["multiplier_bbl"]
    # Session 2: entered at its open → intraday 1.0 only (no gap: flat before).
    assert np.isclose(p["gross"].iloc[1], 1.0 * mult)
    # Session 3: held through the gap (-0.2) and the session (+2.0).
    assert np.isclose(p["gross"].iloc[2], (-0.2 + 2.0) * mult)
    # Session 4: exit at its open → only the gap (+0.1) accrues.
    assert np.isclose(p["gross"].iloc[3], 0.1 * mult)
    assert summarize(p)["sessions"] == 4


def test_overlays():
    f = _frame()
    pos = pd.Series([1, 1, -1, -1, 1, 1], index=f.index, dtype=float)
    rel = pd.Series([f.index[3] + pd.Timedelta(minutes=30)])
    s = ov.eia_standaside_hourly(f, pos, rel, 1, 1)
    # Bars 2..4 are held flat → decisions at rows 1..3 are zeroed.
    assert s.tolist() == [1, 0, 0, 0, 1, 1]
    p = pd.Series([0.6, 0.4, 0.4, 0.6, 0.6, 0.4], index=f.index)
    assert ov.efie_agreement(pos, p).tolist() == [1, 0, -1, 0, 1, 0]
    assert ov.carry_filter(f, pos).tolist() == [1, 1, -1, -1, 1, 1]


def test_signal_csv_alignment(tmp_path):
    f = _frame()
    csv = tmp_path / "my_hourly.csv"
    csv.write_text("time,position\n2026-03-02T15:30:00Z,1\n2026-03-02T17:00:00Z,-1\n")
    s = load_signal_csv(csv, f)
    # tau = 15:00, 16:00, 17:00, …: a 15:30 signal first applies at the 16:00 decision.
    assert s.tolist() == [0, 1, -1, -1, -1, -1]
