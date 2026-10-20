"""Point-in-time joins.

Every observation carries ``available_ts``: the earliest moment it could have been
known. A row decided at time ``τ`` may only see observations with
``available_ts <= τ``. This module is the single place that rule is applied.
"""

from __future__ import annotations

import pandas as pd


def asof_join(
    decision_ts: pd.DatetimeIndex,
    obs: pd.DataFrame,
    columns: list[str],
    prefix: str = "",
    ts_col: str = "available_ts",
) -> pd.DataFrame:
    """Latest observation known at each decision time (backward as-of merge)."""
    left = pd.DataFrame({"decision_ts": pd.DatetimeIndex(decision_ts)})
    left["_order"] = range(len(left))
    right = obs[[ts_col, *columns]].dropna(subset=[ts_col]).sort_values(ts_col, kind="stable")
    right = right.rename(columns={ts_col: "_avail"})
    merged = pd.merge_asof(
        left.sort_values("decision_ts"),
        right,
        left_on="decision_ts",
        right_on="_avail",
        direction="backward",
        allow_exact_matches=True,
    ).sort_values("_order")
    out = merged[[*columns, "_avail"]].rename(columns={"_avail": "known_since"})
    out.index = pd.DatetimeIndex(decision_ts)
    if prefix:
        out = out.add_prefix(prefix)
    return out


def released_within(decision_ts: pd.DatetimeIndex, release_ts: pd.Series, window: pd.Timedelta) -> pd.Series:
    """True where some release became available in ``(τ - window, τ]``."""
    rel = pd.DatetimeIndex(release_ts.dropna().sort_values())
    dec = pd.DatetimeIndex(decision_ts)
    hi = rel.searchsorted(dec, side="right")
    lo = rel.searchsorted(dec - window, side="right")
    return pd.Series(hi > lo, index=dec)
