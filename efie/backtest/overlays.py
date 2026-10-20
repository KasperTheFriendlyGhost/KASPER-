"""Pre-registered overlays: rules that modify a baseline position, never create one.

* ``eia_standaside`` — flat around scheduled EIA releases (the schedule is published in
  advance, so using it carries no look-ahead);
* ``efie_agreement`` — keep the baseline position only when the EFIE model's
  out-of-sample P(up) points the same way;
* ``carry_filter`` — keep longs only in backwardation (M1 > M2) and shorts only in
  contango.

None of these touch sizing rules, the risk governor or HARD LOCK; they are research
filters evaluated on historical data.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

H = pd.Timedelta(hours=1)


def eia_standaside_hourly(frame: pd.DataFrame, pos: pd.Series, release_ts: pd.Series, before: int, after: int) -> pd.Series:
    """Flat while holding any bar from ``before`` bars ahead of the release bar to ``after`` bars after."""
    idx = frame.index
    flat = np.zeros(len(idx), dtype=bool)
    for t in pd.DatetimeIndex(release_ts.dropna()):
        i = idx.searchsorted(t, side="right") - 1
        if i < 0 or not (idx[i] <= t < idx[i] + H):
            continue
        # The position held during bar j is the one decided at row j-1.
        lo, hi = max(i - before - 1, 0), min(i + after - 1, len(idx) - 1)
        flat[lo : hi + 1] = True
    out = pos.copy()
    out[flat] = 0.0
    return out


def eia_standaside_daily(frame: pd.DataFrame, pos: pd.Series, release_ts: pd.Series) -> pd.Series:
    """Flat for any session (open→settle) that contains a scheduled EIA release."""
    days = {pd.Timestamp(t.tz_convert("America/New_York").date()) for t in pd.DatetimeIndex(release_ts.dropna())}
    nxt = pd.Series(frame.index, index=frame.index).shift(-1)
    flat = nxt.isin(days).to_numpy()
    out = pos.copy()
    out[flat] = 0.0
    return out


def efie_agreement(pos: pd.Series, p_up: pd.Series) -> pd.Series:
    p = p_up.reindex(pos.index)
    agree = np.sign(p - 0.5) == np.sign(pos)
    return pos.where(agree.fillna(False), 0.0)


def carry_filter(frame: pd.DataFrame, pos: pd.Series) -> pd.Series:
    spr = frame["ts_spread12"].reindex(pos.index)
    keep = np.sign(spr) == np.sign(pos)
    return pos.where(keep.fillna(False), 0.0)
