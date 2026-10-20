"""The validation gate: what the reports are allowed to show.

Each forecast component is gated separately:

* direction (P(up)) — enough out-of-sample observations, Brier skill vs climatology with
  a 95% block-bootstrap CI whose lower bound is above the threshold, and calibration-in-
  the-large within tolerance;
* expected return — out-of-sample R² vs the climatological mean with a CI lower bound
  above the threshold;
* prediction interval — empirical coverage within tolerance of nominal, and an interval
  (Winkler) score no worse than the climatological interval's.

A component that fails is not shown as a model forecast; the report shows the
climatological value and says why.
"""

from __future__ import annotations

PASS, FAIL, INSUFFICIENT = "VALIDATED", "NOT VALIDATED", "INSUFFICIENT DATA"


def gate(score: dict, cfg: dict, frequency: str) -> dict:
    g = cfg["gate"]
    min_n = g["min_oos_obs_hourly"] if frequency == "hourly" else g["min_oos_obs_daily"]
    out = {}
    if score["n"] < min_n:
        reason = f"only {score['n']} out-of-sample forecasts (< {min_n})"
        return {k: {"verdict": INSUFFICIENT, "reason": reason} for k in ("direction", "expected_return", "interval")}

    lo = score["bss_ci"][0]
    calib_ok = score["calibration_gap"] <= g["max_calibration_gap"]
    if lo > g["min_bss_ci_low"] and calib_ok:
        out["direction"] = {"verdict": PASS, "reason": f"BSS {score['bss']:+.4f}, 95% CI low {lo:+.4f} > {g['min_bss_ci_low']}"}
    else:
        why = []
        if lo <= g["min_bss_ci_low"]:
            hi = score["bss_ci"][1]
            where = "entirely below" if hi < g["min_bss_ci_low"] else "not above"
            why.append(f"BSS {score['bss']:+.4f}, 95% CI [{lo:+.4f}, {hi:+.4f}] {where} {g['min_bss_ci_low']}")
        if not calib_ok:
            why.append(f"calibration gap {score['calibration_gap']:.3f} > {g['max_calibration_gap']}")
        out["direction"] = {"verdict": FAIL, "reason": "; ".join(why)}

    r2lo = score["r2_ci"][0]
    out["expected_return"] = (
        {"verdict": PASS, "reason": f"OOS R² {score['r2_oos']:+.4f}, 95% CI low {r2lo:+.4f}"}
        if r2lo > g["min_r2_ci_low"]
        else {"verdict": FAIL, "reason": f"OOS R² {score['r2_oos']:+.4f}, 95% CI [{r2lo:+.4f}, {score['r2_ci'][1]:+.4f}] not above {g['min_r2_ci_low']}"}
    )

    # The model's interval must be calibrated AND at least as good as the climatological
    # interval (Winkler score); otherwise the climatological interval is shown.
    err = abs(score["coverage"] - score["interval_nominal"])
    ws, wc = score.get("interval_score"), score.get("interval_score_clim")
    better = ws is None or wc is None or ws <= wc
    clim_note = f"; climatology interval coverage {score['coverage_clim']:.3f}" if "coverage_clim" in score else ""
    if err > g["max_coverage_error"]:
        out["interval"] = {"verdict": FAIL, "reason": f"coverage {score['coverage']:.3f} vs nominal {score['interval_nominal']:.2f} (|err| {err:.3f} > {g['max_coverage_error']}){clim_note}"}
    elif not better:
        out["interval"] = {"verdict": FAIL, "reason": f"coverage {score['coverage']:.3f} is calibrated but the interval score {ws:.5f} is worse than climatology's {wc:.5f}{clim_note}"}
    else:
        out["interval"] = {"verdict": PASS, "reason": f"coverage {score['coverage']:.3f} vs nominal {score['interval_nominal']:.2f}; interval score {ws:.5f} ≤ climatology {wc:.5f}"}
    return out
