"""No feature may depend on anything that was not yet known when the decision was taken."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from efie.config import load_config
from efie.features.asof import asof_join, released_within
from efie.features.build import build_daily, build_hourly, truncate
from efie.features.inventories import release_features

TARGET_COLS = ("y_", "gap_next", "intraday_next")


def _feature_cols(df: pd.DataFrame) -> list[str]:
    return [
        c
        for c in df.columns
        if not c.startswith(TARGET_COLS) and (pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_bool_dtype(df[c]))
    ]


def _assert_prefix_equal(full: pd.DataFrame, part: pd.DataFrame, cutoff_tau: pd.Timestamp, min_rows: int = 50):
    rows = part.index[pd.DatetimeIndex(part["tau"]) <= cutoff_tau]
    assert len(rows) > min_rows
    cols = _feature_cols(part)
    a = full.loc[rows, cols].astype(float)
    b = part.loc[rows, cols].astype(float)
    bad = [c for c in cols if not np.allclose(a[c].to_numpy(), b[c].to_numpy(), equal_nan=True, rtol=1e-9, atol=1e-12)]
    assert not bad, f"features changed when future data was removed: {bad[:10]}"


def test_asof_join_never_sees_future():
    dec = pd.date_range("2026-01-01", periods=10, freq="1h", tz="UTC")
    obs = pd.DataFrame({"available_ts": [dec[2], dec[5] + pd.Timedelta(minutes=1), dec[7]], "x": [1.0, 2.0, 3.0]})
    j = asof_join(dec, obs, ["x"])
    assert np.isnan(j["x"].iloc[0]) and np.isnan(j["x"].iloc[1])
    assert j["x"].iloc[2] == 1.0  # exact availability counts as known
    assert j["x"].iloc[5] == 1.0  # one minute too early for the second observation
    assert j["x"].iloc[6] == 2.0 and j["x"].iloc[7] == 3.0
    assert (j["known_since"].dropna() <= pd.Series(dec, index=dec)[j["known_since"].notna()]).all()


def test_released_within():
    dec = pd.date_range("2026-01-01", periods=4, freq="1h", tz="UTC")
    rel = pd.Series([dec[1] - pd.Timedelta(minutes=30)])
    m = released_within(dec, rel, pd.Timedelta(hours=1))
    assert m.tolist() == [False, True, False, False]


def test_surprise_scaling_uses_only_prior_releases(synthetic_md):
    ev = synthetic_md.events
    f1 = release_features(ev)
    ev2 = ev.copy()
    last = ev2.index[(ev2["series"] == "eia_crude")][-1]
    ev2.loc[last, "actual"] = 1e12  # change the newest release only
    f2 = release_features(ev2)
    a = f1[f1["series"] == "eia_crude"].iloc[:-1][["surprise_z", "change_z"]]
    b = f2[f2["series"] == "eia_crude"].iloc[:-1][["surprise_z", "change_z"]]
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))


@pytest.mark.parametrize("cut_days", [40, 75, 100])
def test_hourly_features_identical_under_truncation(synthetic_md, cut_days):
    cfg = load_config()
    T = synthetic_md.hourly["CL1"].index[0] + pd.Timedelta(days=cut_days, hours=7)
    full = build_hourly(synthetic_md, cfg)
    part = build_hourly(truncate(synthetic_md, T), cfg)
    _assert_prefix_equal(full, part, T)


@pytest.mark.parametrize("cut_days", [60, 100])
def test_daily_features_identical_under_truncation(synthetic_md, cut_days):
    cfg = load_config()
    T = synthetic_md.hourly["CL1"].index[0] + pd.Timedelta(days=cut_days, hours=3)
    full = build_daily(synthetic_md, cfg)
    part = build_daily(truncate(synthetic_md, T), cfg)
    _assert_prefix_equal(full, part, T, min_rows=20)


def test_targets_start_after_decision(synthetic_md):
    h = build_hourly(synthetic_md, load_config())
    v = h[h["y_1_valid"]]
    assert (pd.DatetimeIndex(v["y_1_end"]) > pd.DatetimeIndex(v["tau"])).all()
    # The 1-bar target is the next bar's return, never the decision bar's own.
    np.testing.assert_allclose(v["y_1"].to_numpy(), h["r"].shift(-1).loc[v.index].to_numpy())


def test_real_snapshot_truncation(real_md):
    cfg = load_config()
    T = pd.Timestamp("2026-10-15 17:00", tz="UTC")  # the hour after an EIA release
    full = build_hourly(real_md, cfg)
    part = build_hourly(truncate(real_md, T), cfg)
    _assert_prefix_equal(full, part, T)
    row = part.iloc[-1]
    assert row["tau"] <= T
    assert row["inv_eia_crude_age_h"] >= 0
