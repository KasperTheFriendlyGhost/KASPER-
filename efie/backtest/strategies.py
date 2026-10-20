"""Reference technical baselines and the loader for your own strategy signals.

The reference baselines are NOT your MCL strategies. They exist so the overlay tests can
run end to end until your own signal exports are supplied; their results say nothing
about your strategies.

Positions are in MCL contracts, decided at a bar's close and held over the next bar.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def _adjusted_index(r: pd.Series) -> pd.Series:
    return np.exp(r.fillna(0.0).cumsum())


def ema_trend(frame: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    adj = _adjusted_index(frame["r"])
    s = np.sign(adj.ewm(span=fast, adjust=False).mean() - adj.ewm(span=slow, adjust=False).mean())
    s.iloc[:slow] = 0.0
    return s.rename(f"ema_{fast}_{slow}")


def donchian(frame: pd.DataFrame, n: int) -> pd.Series:
    adj = _adjusted_index(frame["r"])
    hi = adj.shift(1).rolling(n).max()
    lo = adj.shift(1).rolling(n).min()
    sig = pd.Series(np.where(adj > hi, 1.0, np.where(adj < lo, -1.0, np.nan)), index=frame.index)
    return sig.ffill().fillna(0.0).rename(f"donchian_{n}")


def momentum(frame: pd.DataFrame, n: int) -> pd.Series:
    s = np.sign(frame["r"].rolling(n).sum()).fillna(0.0)
    return s.rename(f"momentum_{n}")


def load_signal_csv(path: Path, frame: pd.DataFrame) -> pd.Series:
    """Your strategy's positions, aligned to EFIE decision times.

    CSV columns: ``time`` (Unix seconds, or ISO-8601 with an offset; naive times are UTC)
    and ``position`` (signed MCL contracts). Each row means "from this time on, hold this
    position". At each decision time ``tau`` the latest row with ``time <= tau`` applies,
    so a signal is never used before it existed.
    """
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    t = df[cols["time"]]
    ts = pd.to_datetime(t.astype("int64"), unit="s", utc=True) if pd.api.types.is_numeric_dtype(t) else pd.to_datetime(t, utc=True)
    sig = pd.DataFrame({"available_ts": ts, "position": df[cols["position"]].astype(float)}).sort_values("available_ts")
    left = pd.DataFrame({"tau": pd.DatetimeIndex(frame["tau"])})
    m = pd.merge_asof(left, sig, left_on="tau", right_on="available_ts", direction="backward")
    return pd.Series(m["position"].fillna(0.0).to_numpy(), index=frame.index, name=Path(path).stem)
