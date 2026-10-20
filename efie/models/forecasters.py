"""Forecast models. Hyperparameters are fixed in the config before any test data is seen.

* ``clim`` — unconditional: P(up) and mean return from the training window; the interval
  is the training distribution of vol-normalised returns scaled by current volatility.
* linear models — L2 logistic regression for P(up) and ridge regression for the
  vol-normalised return, on standardised features; intervals are split-conformal on
  vol-normalised residuals (fit on the first part of the window, residual quantiles on the
  last ``calibration_fraction``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, Ridge

CLIP = 5.0


@dataclass
class Scaler:
    mean: pd.Series
    std: pd.Series

    @classmethod
    def fit(cls, X: pd.DataFrame) -> Scaler:
        sd = X.std().replace(0, np.nan)
        return cls(X.mean(), sd)

    def transform(self, X: pd.DataFrame) -> np.ndarray:
        Z = (X - self.mean) / self.std
        return Z.fillna(0.0).clip(-CLIP, CLIP).to_numpy(float)


def _usable(cols: list[str], train: pd.DataFrame, min_obs: int = 50) -> list[str]:
    """Columns with enough non-missing training values to estimate anything."""
    return [c for c in cols if train[c].notna().sum() >= min_obs and train[c].std() > 0]


def _quantiles(z: np.ndarray, nominal: float) -> tuple[float, float]:
    a = (1 - nominal) / 2
    return float(np.quantile(z, a)), float(np.quantile(z, 1 - a))


def fit_predict_clim(train: pd.DataFrame, test: pd.DataFrame, scale_col: str, horizon: int, nominal: float, calib_frac: float) -> pd.DataFrame:
    y = train["y"].to_numpy(float)
    s_tr = train[scale_col].to_numpy(float) * np.sqrt(horizon)
    mu = float(np.mean(y))
    p = float(np.mean(y > 0))
    cal = slice(int(len(train) * (1 - calib_frac)), None)
    z = ((y - mu) / s_tr)[cal]
    z = z[np.isfinite(z)]
    ql, qh = _quantiles(z, nominal)
    s_te = test[scale_col].to_numpy(float) * np.sqrt(horizon)
    return pd.DataFrame(
        {"p_clim": p, "mu_clim": mu, "lo_clim": mu + ql * s_te, "hi_clim": mu + qh * s_te},
        index=test.index,
    )


def fit_predict_linear(
    name: str,
    cols: list[str],
    train: pd.DataFrame,
    test: pd.DataFrame,
    scale_col: str,
    horizon: int,
    C: float,
    alpha: float,
    nominal: float,
    calib_frac: float,
) -> tuple[pd.DataFrame, dict]:
    cols = _usable(cols, train)
    y = train["y"].to_numpy(float)
    s_tr = train[scale_col].to_numpy(float) * np.sqrt(horizon)
    s_te = test[scale_col].to_numpy(float) * np.sqrt(horizon)
    yn = y / s_tr

    def _fit(tr: pd.DataFrame, yy: np.ndarray, yyn: np.ndarray):
        sc = Scaler.fit(tr[cols])
        X = sc.transform(tr[cols])
        clf = LogisticRegression(C=C, max_iter=2000).fit(X, (yy > 0).astype(int)) if len(set(yy > 0)) > 1 else None
        reg = Ridge(alpha=alpha).fit(X, yyn)
        return sc, clf, reg

    sc, clf, reg = _fit(train, y, yn)
    Xte = sc.transform(test[cols])
    p = clf.predict_proba(Xte)[:, 1] if clf is not None else np.full(len(test), float(np.mean(y > 0)))
    mu = reg.predict(Xte) * s_te

    # Split-conformal on vol-normalised residuals.
    k = int(len(train) * (1 - calib_frac))
    sc1, _, reg1 = _fit(train.iloc[:k], y[:k], yn[:k])
    cal = train.iloc[k:]
    resid = yn[k:] - reg1.predict(sc1.transform(cal[cols]))
    resid = resid[np.isfinite(resid)]
    ql, qh = _quantiles(resid, nominal)
    out = pd.DataFrame(
        {f"p_{name}": p, f"mu_{name}": mu, f"lo_{name}": mu + ql * s_te, f"hi_{name}": mu + qh * s_te},
        index=test.index,
    )
    coefs = {
        "features": cols,
        "logit_coef": (clf.coef_[0].tolist() if clf is not None else []),
        "ridge_coef": reg.coef_.tolist(),
    }
    return out, coefs
