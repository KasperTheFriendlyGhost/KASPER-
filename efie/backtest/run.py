"""Do the fundamental overlays improve technical MCL strategies after costs?

For every baseline (reference baselines, plus any strategy signal files you supply) and
every pre-registered overlay, the overlay's session P&L is compared with the baseline's
over the same out-of-sample window (where EFIE forecasts exist). The test statistic is
the mean session P&L difference with a moving-block bootstrap CI; one-sided p-values are
Holm–Bonferroni adjusted across the whole family.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from efie.backtest import overlays as ov
from efie.backtest.engine import daily_pnl, hourly_pnl, session_series, summarize
from efie.backtest.strategies import donchian, ema_trend, load_signal_csv, momentum
from efie.config import load_config
from efie.features.build import MarketData, build_daily, build_hourly
from efie.paths import EVIDENCE_DIR, PROCESSED_DIR
from efie.validation.hypotheses import holm
from efie.validation.metrics import bootstrap


def _oos_p(name: str) -> pd.Series | None:
    p = PROCESSED_DIR / f"oos_predictions_{name}.csv.gz"
    if not p.exists():
        return None
    df = pd.read_csv(p, index_col=0)
    idx = pd.to_datetime(df.index, utc=True) if name != "next_session" else pd.to_datetime(df.index)
    return pd.Series(df["p_tech_fund"].to_numpy(), index=idx)


def compare(base: pd.Series, other: pd.Series, block: int, reps: int, seed: int) -> dict:
    j = pd.concat([base.rename("b"), other.rename("o")], axis=1).fillna(0.0)
    d = (j["o"] - j["b"]).to_numpy()
    bs = bootstrap(np.mean, (d,), block, reps, seed)

    def _sh(x):
        s = x.std()
        return x.mean() / s * np.sqrt(252) if s > 0 else np.nan

    sb = bootstrap(lambda a, b: _sh(b) - _sh(a), (j["b"].to_numpy(), j["o"].to_numpy()), block, reps, seed + 1)
    return {
        "sessions": int(len(d)),
        "mean_diff_usd_per_session": float(d.mean()),
        "ci": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
        "p_one_sided": float((bs <= 0).mean()),
        "sharpe_diff": float(_sh(j["o"].to_numpy()) - _sh(j["b"].to_numpy())),
        "sharpe_diff_ci": [float(np.nanpercentile(sb, 2.5)), float(np.nanpercentile(sb, 97.5))],
    }


def run_backtests(md: MarketData, cfg: dict | None = None, signal_files: list[Path] | None = None, write: bool = True) -> dict:
    cfg = cfg or load_config()
    b, v = cfg["backtest"], cfg["validation"]
    stress = cfg["costs"]["stress_multiplier"]
    reps, seed = v["bootstrap_reps"], v["seed"]
    h, d = build_hourly(md, cfg), build_daily(md, cfg)
    eia_ts = md.events.loc[md.events["series"] == "eia_crude", "release_ts"]

    p_h, p_d = _oos_p("1h"), _oos_p("next_session")
    h_start = p_h.index.min() if p_h is not None else h.index[cfg["validation"]["hourly_min_train"]]
    d_start = p_d.index.min() if p_d is not None else d.index[cfg["validation"]["daily_min_train"]]
    hw, dw = h[h.index >= h_start], d[d.index >= d_start]

    baselines = {
        "hourly": {
            f"REF ema_{b['ema_fast']}_{b['ema_slow']} (hourly)": ema_trend(h, b["ema_fast"], b["ema_slow"]),
            f"REF donchian_{b['donchian_bars']} (hourly)": donchian(h, b["donchian_bars"]),
        },
        "daily": {f"REF momentum_{b['daily_momentum_days']} (daily)": momentum(d, b["daily_momentum_days"])},
    }
    for f in signal_files or []:
        f = Path(f)
        freq = "daily" if "daily" in f.stem.lower() else "hourly"
        baselines[freq][f"USER {f.stem} ({freq})"] = load_signal_csv(f, h if freq == "hourly" else d)

    results = {"window": {"hourly_start": str(h_start), "daily_start": str(d_start)}, "strategies": {}, "tests": {}}
    pvals = {}
    for freq, strategies in baselines.items():
        frame = hw if freq == "hourly" else dw
        pnl_fn = hourly_pnl if freq == "hourly" else daily_pnl
        p_up = p_h if freq == "hourly" else p_d
        for name, pos in strategies.items():
            pos = pos.reindex(frame.index).fillna(0.0)
            variants = {"baseline": pos}
            if freq == "hourly":
                variants["eia_standaside"] = ov.eia_standaside_hourly(
                    frame, pos, eia_ts, b["eia_standaside_bars_before"], b["eia_standaside_bars_after"]
                )
            else:
                variants["eia_standaside"] = ov.eia_standaside_daily(frame, pos, eia_ts)
            if p_up is not None:
                variants["efie_agreement"] = ov.efie_agreement(pos, p_up)
            variants["carry_filter"] = ov.carry_filter(frame, pos)
            res, series = {}, {}
            for vname, vp in variants.items():
                pnl = pnl_fn(frame, vp, cfg)
                pnl_s = pnl_fn(frame, vp, cfg, stress)
                res[vname] = {"costs_1x": summarize(pnl), f"costs_{stress:g}x": summarize(pnl_s)}
                if freq == "daily" and "roll_uncertain" in frame:
                    keep = ~frame["roll_uncertain"].reindex(pnl.index).fillna(False).astype(bool)
                    res[vname]["costs_1x_excluding_uncertain_roll_windows"] = summarize(pnl[keep])
                series[vname] = session_series(pnl)
            results["strategies"][name] = res
            for vname in variants:
                if vname == "baseline":
                    continue
                key = f"{name} :: {vname}"
                results["tests"][key] = compare(series["baseline"], series[vname], 10, reps, seed)
                pvals[key] = results["tests"][key]["p_one_sided"]
    adj = holm(pvals, b["family_alpha"])
    for k in results["tests"]:
        results["tests"][k].update({"p_holm": adj[k]["p_holm"], "significant_after_holm": adj[k]["reject"]})
    results["costs"] = {
        "commission_per_side_usd": cfg["costs"]["commission_per_side_usd"],
        "slippage_ticks_per_side": cfg["costs"]["slippage_ticks_per_side"],
        "tick_value_usd": cfg["instrument"]["tick_value_usd"],
        "stress_multiplier": stress,
    }
    if write:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        (EVIDENCE_DIR / "backtest.json").write_text(json.dumps(results, indent=2))
    return results
