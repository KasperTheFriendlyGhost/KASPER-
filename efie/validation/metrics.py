"""Forecast scoring and dependence-robust uncertainty.

Overlapping or autocorrelated observations make i.i.d. confidence intervals too narrow,
so every interval here comes from a moving-block bootstrap of the per-observation scores.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    block = max(1, min(block, n))
    starts = rng.integers(0, n - block + 1, size=int(np.ceil(n / block)))
    return (starts[:, None] + np.arange(block)).ravel()[:n]


def bootstrap(stat, arrays: tuple[np.ndarray, ...], block: int, reps: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = len(arrays[0])
    out = np.empty(reps)
    for k in range(reps):
        idx = block_indices(n, block, rng)
        out[k] = stat(*(a[idx] for a in arrays))
    return out


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def auc(p: np.ndarray, y: np.ndarray) -> float:
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    ranks = pd.Series(np.concatenate([pos, neg])).rank().to_numpy()
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def _bss(a: np.ndarray, b: np.ndarray) -> float:
    s = a.sum()
    return float(1.0 - b.sum() / s) if s > 0 else float("nan")


def _r2(y: np.ndarray, yhat: np.ndarray, ybar: np.ndarray) -> float:
    d = ((y - ybar) ** 2).sum()
    return float(1.0 - ((y - yhat) ** 2).sum() / d) if d > 0 else float("nan")


def reliability(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    cut = np.digitize(p, edges[1:-1])
    rows = []
    for b in range(bins):
        m = cut == b
        if m.any():
            rows.append({"bin": b, "n": int(m.sum()), "mean_p": float(p[m].mean()), "freq_up": float(y[m].mean())})
    return rows


def interval_score(y: np.ndarray, lo: np.ndarray, hi: np.ndarray, nominal: float) -> float:
    """Mean Winkler interval score (lower is better): width plus penalties for misses."""
    a = 1.0 - nominal
    pen = (2.0 / a) * (np.clip(lo - y, 0, None) + np.clip(y - hi, 0, None))
    return float(np.mean((hi - lo) + pen))


def score_forecasts(
    pred: pd.DataFrame,
    model: str,
    block: int,
    reps: int,
    seed: int,
    nominal: float,
) -> dict:
    """Out-of-sample scores of ``model`` against the climatology columns in ``pred``."""
    y = pred["y"].to_numpy(float)
    up = (y > 0).astype(float)
    p = pred[f"p_{model}"].to_numpy(float)
    pc = pred["p_clim"].to_numpy(float)
    mu = pred[f"mu_{model}"].to_numpy(float)
    mc = pred["mu_clim"].to_numpy(float)
    lo, hi = pred[f"lo_{model}"].to_numpy(float), pred[f"hi_{model}"].to_numpy(float)
    a, b = (pc - up) ** 2, (p - up) ** 2
    bss = _bss(a, b)
    bss_bs = bootstrap(_bss, (a, b), block, reps, seed)
    r2 = _r2(y, mu, mc)
    r2_bs = bootstrap(_r2, (y, mu, mc), block, reps, seed + 1)
    cover = ((y >= lo) & (y <= hi)).astype(float)
    lc, hc = pred["lo_clim"].to_numpy(float), pred["hi_clim"].to_numpy(float)
    cov_bs = bootstrap(np.mean, (cover,), block, reps, seed + 2)
    hit = (np.sign(p - 0.5) == np.sign(up - 0.5)).astype(float)
    return {
        "model": model,
        "n": int(len(y)),
        "start": str(pred.index[0]),
        "end": str(pred.index[-1]),
        "up_rate": float(up.mean()),
        "brier": brier(p, up),
        "brier_clim": brier(pc, up),
        "bss": bss,
        "bss_ci": [float(np.nanpercentile(bss_bs, 2.5)), float(np.nanpercentile(bss_bs, 97.5))],
        "log_loss": log_loss(p, up),
        "log_loss_clim": log_loss(pc, up),
        "auc": auc(p, up),
        "hit_rate": float(hit.mean()),
        "mean_p": float(p.mean()),
        "calibration_gap": float(abs(p.mean() - up.mean())),
        "reliability": reliability(p, up),
        "r2_oos": r2,
        "r2_ci": [float(np.nanpercentile(r2_bs, 2.5)), float(np.nanpercentile(r2_bs, 97.5))],
        "interval_nominal": nominal,
        "coverage": float(cover.mean()),
        "coverage_ci": [float(np.percentile(cov_bs, 2.5)), float(np.percentile(cov_bs, 97.5))],
        "mean_width": float(np.mean(hi - lo)),
        "interval_score": interval_score(y, lo, hi, nominal),
        "interval_score_clim": interval_score(y, lc, hc, nominal),
        "coverage_clim": float(((y >= lc) & (y <= hc)).mean()),
    }


def paired_brier_difference(pred: pd.DataFrame, m1: str, m0: str, block: int, reps: int, seed: int) -> dict:
    """Mean Brier(m0) − Brier(m1): positive means ``m1`` is better. Block-bootstrap CI."""
    up = (pred["y"].to_numpy(float) > 0).astype(float)
    d = (pred[f"p_{m0}"].to_numpy(float) - up) ** 2 - (pred[f"p_{m1}"].to_numpy(float) - up) ** 2
    bs = bootstrap(np.mean, (d,), block, reps, seed)
    return {
        "better": m1,
        "than": m0,
        "mean_diff": float(d.mean()),
        "ci": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
        "p_value_one_sided": float((bs <= 0).mean()),
    }


def by_period(pred: pd.DataFrame, model: str, freq: str = "YE") -> list[dict]:
    up = (pred["y"] > 0).astype(float)
    a = (pred["p_clim"] - up) ** 2
    b = (pred[f"p_{model}"] - up) ** 2
    idx = pd.DatetimeIndex(pred.index)
    idx = idx.tz_convert(None) if idx.tz is not None else idx
    g = pd.DataFrame({"a": a.to_numpy(), "b": b.to_numpy(), "y": pred["y"].to_numpy()}, index=idx).groupby(pd.Grouper(freq=freq))
    rows = []
    for k, x in g:
        if len(x) >= 20:
            rows.append({"period": str(k.date()), "n": int(len(x)), "bss": float(1 - x["b"].sum() / x["a"].sum())})
    return rows
