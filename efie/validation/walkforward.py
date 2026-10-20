"""Purged, expanding-window walk-forward evaluation.

At each refit point the model is trained only on rows whose *target* had fully resolved
before the first decision in the test block (``y_end <= tau_test_start``), so no training
label overlaps the test period. Test blocks never overlap and are scored once.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from efie.models.forecasters import fit_predict_clim, fit_predict_linear


@dataclass
class Spec:
    name: str  # e.g. "1h"
    target: str  # column holding the target return
    valid: str  # boolean column: target is usable
    end: str  # column holding the target's resolution time
    horizon: int  # horizon in rows (for vol scaling)
    scale_col: str  # per-row volatility used to normalise returns
    min_train: int
    refit_every: int
    feature_sets: dict[str, list[str]] = field(default_factory=dict)


def usable_rows(df: pd.DataFrame, spec: Spec) -> pd.DataFrame:
    m = df[spec.valid].fillna(False).astype(bool) & df[spec.target].notna() & df[spec.scale_col].notna()
    out = df[m].copy()
    out["y"] = out[spec.target]
    return out


def walk_forward(df: pd.DataFrame, spec: Spec, cfg: dict) -> tuple[pd.DataFrame, list[dict]]:
    v = cfg["validation"]
    data = usable_rows(df, spec)
    n = len(data)
    preds, fits = [], []
    for start in range(spec.min_train, n, spec.refit_every):
        test = data.iloc[start : start + spec.refit_every]
        t0 = test["tau"].iloc[0]
        train = data.iloc[:start]
        train = train[train[spec.end] <= t0]
        block = [
            fit_predict_clim(train, test, spec.scale_col, spec.horizon, v["interval_nominal"], v["calibration_fraction"])
        ]
        for name, cols in spec.feature_sets.items():
            out, coefs = fit_predict_linear(
                name,
                cols,
                train,
                test,
                spec.scale_col,
                spec.horizon,
                v["logistic_C"],
                v["ridge_alpha"],
                v["interval_nominal"],
                v["calibration_fraction"],
            )
            block.append(out)
            fits.append({"refit_at": str(t0), "model": name, "n_train": int(len(train)), **coefs})
        b = pd.concat(block, axis=1)
        b["y"] = test["y"]
        b["tau"] = test["tau"]
        preds.append(b)
    pred = pd.concat(preds) if preds else pd.DataFrame()
    return pred, fits


def fit_latest(df: pd.DataFrame, spec: Spec, cfg: dict, asof_tau: pd.Timestamp, row: pd.DataFrame) -> pd.DataFrame:
    """Forecast for ``row`` using every target that had resolved by ``asof_tau``."""
    v = cfg["validation"]
    data = usable_rows(df, spec)
    train = data[data[spec.end] <= asof_tau]
    block = [fit_predict_clim(train, row, spec.scale_col, spec.horizon, v["interval_nominal"], v["calibration_fraction"])]
    for name, cols in spec.feature_sets.items():
        out, _ = fit_predict_linear(
            name, cols, train, row, spec.scale_col, spec.horizon, v["logistic_C"], v["ridge_alpha"], v["interval_nominal"], v["calibration_fraction"]
        )
        block.append(out)
    out = pd.concat(block, axis=1)
    out["n_train"] = len(train)
    return out


def coef_summary(fits: list[dict], model: str) -> pd.DataFrame:
    """Average standardised coefficients across refits (how the model leaned, on average)."""
    rows = []
    for f in fits:
        if f["model"] != model:
            continue
        for feat, cl, cr in zip(f["features"], f["logit_coef"] or [np.nan] * len(f["features"]), f["ridge_coef"]):
            rows.append({"feature": feat, "logit": cl, "ridge": cr})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).groupby("feature").agg(
        logit_mean=("logit", "mean"),
        logit_sign_stability=("logit", lambda s: float(np.mean(np.sign(s) == np.sign(s.mean())))),
        ridge_mean=("ridge", "mean"),
        refits=("logit", "size"),
    )
    return df.reindex(df["logit_mean"].abs().sort_values(ascending=False).index)
