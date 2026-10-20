"""Run the walk-forward validation for every horizon and write the evidence.

Pre-registered comparison (fixed before running):

* ``clim``      — unconditional benchmark;
* ``tech``      — price-only features (the stand-in for "technical" information);
* ``tech_fund`` — the EFIE model: technical + term structure, cracks, inventories,
  refinery runs, freight and Brent–WTI.

The question "do the fundamentals add anything?" is answered by ``tech_fund`` vs
``tech`` (paired Brier difference), not by picking whichever model looks best.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from efie.config import load_config
from efie.features.build import FEATURE_PREFIXES, MarketData, build_daily, build_hourly, feature_columns
from efie.paths import EVIDENCE_DIR, PROCESSED_DIR
from efie.validation.gate import gate
from efie.validation.metrics import by_period, paired_brier_difference, score_forecasts
from efie.validation.walkforward import Spec, coef_summary, walk_forward

FUND = ("ts_", "crk_", "frt_", "arb_", "inv_", "rig_")
PRIMARY = "tech_fund"


def specs(hourly: pd.DataFrame, daily: pd.DataFrame, cfg: dict) -> list[tuple[Spec, pd.DataFrame, str]]:
    v = cfg["validation"]
    h_tech = feature_columns(hourly, ("tech_",))
    h_all = feature_columns(hourly, FEATURE_PREFIXES)
    d_tech = feature_columns(daily, ("tech_",))
    d_all = feature_columns(daily, FEATURE_PREFIXES)
    hs = {"tech": h_tech, "tech_fund": h_all}
    ds = {"tech": d_tech, "tech_fund": d_all}
    return [
        (Spec("1h", "y_1", "y_1_valid", "y_1_end", 1, "tech_vol_24", v["hourly_min_train"], v["hourly_refit_every"], hs), hourly, "hourly"),
        (Spec("4h", "y_4", "y_4_valid", "y_4_end", 4, "tech_vol_24", v["hourly_min_train"], v["hourly_refit_every"], hs), hourly, "hourly"),
        (
            Spec("next_session", "y_next", "y_next_valid", "y_next_end", 1, "tech_vol_20", v["daily_min_train"], v["daily_refit_every"], ds),
            daily,
            "daily",
        ),
    ]


def run_validation(md: MarketData, cfg: dict | None = None, write: bool = True) -> dict:
    cfg = cfg or load_config()
    v = cfg["validation"]
    hourly, daily = build_hourly(md, cfg), build_daily(md, cfg)
    results = {"snapshot": str(md.snapshot), "config": {"validation": v, "gate": cfg["gate"]}, "horizons": {}}
    all_preds = {}
    for spec, df, freq in specs(hourly, daily, cfg):
        pred, fits = walk_forward(df, spec, cfg)
        all_preds[spec.name] = pred
        block = v["block_len_hourly"] if freq == "hourly" else v["block_len_daily"]
        # Overlapping 4h targets need blocks at least as long as the overlap.
        block = max(block, spec.horizon * 6)
        scores = {
            m: score_forecasts(pred, m, block, v["bootstrap_reps"], v["seed"], v["interval_nominal"])
            for m in ("clim", "tech", "tech_fund")
        }
        inc = {
            "tech_fund_vs_tech": paired_brier_difference(pred, "tech_fund", "tech", block, v["bootstrap_reps"], v["seed"] + 7),
            "tech_fund_vs_clim": paired_brier_difference(pred, "tech_fund", "clim", block, v["bootstrap_reps"], v["seed"] + 8),
            "tech_vs_clim": paired_brier_difference(pred, "tech", "clim", block, v["bootstrap_reps"], v["seed"] + 9),
        }
        coefs = coef_summary(fits, PRIMARY)
        results["horizons"][spec.name] = {
            "frequency": freq,
            "target": spec.target,
            "n_features": {k: len(c) for k, c in spec.feature_sets.items()},
            "scores": scores,
            "gate": {m: gate(scores[m], cfg, freq) for m in ("tech", "tech_fund")},
            "incremental": inc,
            "by_year": {m: by_period(pred, m) for m in ("tech", "tech_fund")},
            "top_coefficients": coefs.head(15).reset_index().to_dict(orient="records") if len(coefs) else [],
            "refits": len({f["refit_at"] for f in fits}),
        }
    if write:
        PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        for k, p in all_preds.items():
            p.to_csv(PROCESSED_DIR / f"oos_predictions_{k}.csv.gz")
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        (EVIDENCE_DIR / "validation.json").write_text(json.dumps(results, indent=2, default=_json_default))
    return results


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, (pd.Timestamp,)):
        return str(o)
    return str(o)


def load_validation(path: Path | None = None) -> dict | None:
    p = path or (EVIDENCE_DIR / "validation.json")
    return json.loads(p.read_text()) if p.exists() else None
