"""Weekly inventory releases → point-in-time surprise features.

For each release (one row per series per release):

* ``surprise`` = first-print actual − consensus (only where a consensus was polled);
* ``surprise_z`` = surprise ÷ s.d. of that series' *previous* surprises (52 releases,
  at least 12), so the scale never uses the release being scaled or anything later;
* ``change_z`` = (actual − mean of previous 52 actuals) ÷ their s.d. — used for series
  without a consensus (Cushing, refinery runs, imports, production);
* ``seasonal_dev_z`` = actual − mean of actuals in the same ISO week (±1) over the
  previous five years, scaled like ``change_z``.

``available_ts`` = release timestamp + the configured buffer.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WINDOW = 52
MIN_PERIODS = 12


def _prior_rolling(x: pd.Series, fn: str) -> pd.Series:
    return getattr(x.shift(1).rolling(WINDOW, min_periods=MIN_PERIODS), fn)()


def _seasonal(group: pd.DataFrame) -> pd.Series:
    """Mean of the same ISO week ±1 over the prior five years, release by release."""
    dates = group["release_ts"]
    weeks = dates.dt.isocalendar().week.astype(int).to_numpy()
    years = dates.dt.isocalendar().year.astype(int).to_numpy()
    vals = group["actual"].to_numpy(dtype=float)
    out = np.full(len(group), np.nan)
    for i in range(len(group)):
        mask = (years < years[i]) & (years >= years[i] - 5)
        wk = np.abs(weeks - weeks[i])
        mask &= np.minimum(wk, 52 - wk) <= 1
        mask[i:] = False
        if mask.sum() >= 8:
            out[i] = np.nanmean(vals[mask])
    return pd.Series(out, index=group.index)


def release_features(events: pd.DataFrame, buffer_minutes: int = 5) -> pd.DataFrame:
    ev = events.dropna(subset=["actual"]).copy()
    # Two weeks can be published at the same moment (catch-up after a delay): order them by
    # reference week so the as-of join sees the most recent week last.
    ev = ev.sort_values(["series", "release_ts", "reference_date"], kind="stable")
    ev["available_ts"] = ev["release_ts"] + pd.Timedelta(minutes=buffer_minutes)
    parts = []
    for _, g in ev.groupby("series", sort=False):
        g = g.copy()
        g["surprise"] = g["actual"] - g["consensus"]
        sd_s = _prior_rolling(g["surprise"], "std")
        g["surprise_z"] = g["surprise"] / sd_s
        mu_a, sd_a = _prior_rolling(g["actual"], "mean"), _prior_rolling(g["actual"], "std")
        g["change_z"] = (g["actual"] - mu_a) / sd_a
        seas = _seasonal(g)
        g["seasonal_dev"] = g["actual"] - seas
        g["seasonal_dev_z"] = g["seasonal_dev"] / sd_a
        parts.append(g)
    out = pd.concat(parts).sort_values(["available_ts", "reference_date"], kind="stable").reset_index(drop=True)
    return out.replace([np.inf, -np.inf], np.nan)


def wide_by_release(feat: pd.DataFrame, series: str, cols: list[str]) -> pd.DataFrame:
    g = feat[feat["series"] == series]
    return g[["available_ts", "release_ts", "reference_date", *cols]].reset_index(drop=True)


def eia_minus_api(feat: pd.DataFrame) -> pd.DataFrame:
    """EIA crude change minus the API crude change published for the same week.

    Available when the EIA figure is (the API figure always comes first).
    """
    e = feat[feat["series"] == "eia_crude"][["available_ts", "reference_date", "actual"]]
    a = feat[feat["series"] == "api_crude"][["reference_date", "actual"]]
    m = e.merge(a, on="reference_date", suffixes=("_eia", "_api"), how="inner")
    m["eia_minus_api"] = m["actual_eia"] - m["actual_api"]
    sd = m["eia_minus_api"].shift(1).rolling(WINDOW, min_periods=MIN_PERIODS).std()
    m["eia_minus_api_z"] = m["eia_minus_api"] / sd
    return m[["available_ts", "reference_date", "eia_minus_api", "eia_minus_api_z"]]
