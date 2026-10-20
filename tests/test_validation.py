import numpy as np
import pandas as pd
import pytest

from efie.config import load_config
from efie.validation import walkforward as wf
from efie.validation.gate import FAIL, INSUFFICIENT, PASS, gate
from efie.validation.hypotheses import corr_test, holm
from efie.validation.metrics import auc, bootstrap, brier, paired_brier_difference, score_forecasts


def _pred(n=3000, seed=0, skill=0.0):
    rng = np.random.default_rng(seed)
    y = rng.normal(0, 1, n)
    p_clim = np.full(n, 0.5)
    p_m = np.clip(0.5 + skill * np.sign(y) + rng.normal(0, 0.01, n), 0.01, 0.99)
    idx = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    d = pd.DataFrame({"y": y, "p_clim": p_clim, "mu_clim": 0.0, "lo_clim": -1.2816, "hi_clim": 1.2816}, index=idx)
    d["p_m"], d["mu_m"], d["lo_m"], d["hi_m"] = p_m, 0.0, -1.2816, 1.2816
    return d


def test_brier_and_auc():
    y = np.array([1, 0, 1, 0.0])
    assert brier(np.array([1, 0, 1, 0.0]), y) == 0
    assert brier(np.full(4, 0.5), y) == 0.25
    assert auc(np.array([0.9, 0.1, 0.8, 0.2]), y) == 1.0


def test_bootstrap_reproducible():
    x = np.arange(100.0)
    a = bootstrap(np.mean, (x,), 10, 50, 1)
    b = bootstrap(np.mean, (x,), 10, 50, 1)
    np.testing.assert_array_equal(a, b)


def test_score_no_skill_vs_skill():
    s0 = score_forecasts(_pred(skill=0.0), "m", 24, 300, 1, 0.8)
    s1 = score_forecasts(_pred(skill=0.1), "m", 24, 300, 1, 0.8)
    assert s0["bss_ci"][0] < 0 < s0["bss_ci"][1] or abs(s0["bss"]) < 0.01
    assert s1["bss"] > 0 and s1["bss_ci"][0] > 0
    assert abs(s1["coverage"] - 0.8) < 0.03


def test_gate_verdicts():
    cfg = load_config()
    s1 = score_forecasts(_pred(skill=0.1), "m", 24, 300, 1, 0.8)
    g = gate(s1, cfg, "hourly")
    assert g["direction"]["verdict"] == PASS
    assert g["expected_return"]["verdict"] == FAIL  # mu is zero: no return skill
    assert g["interval"]["verdict"] == PASS
    s0 = score_forecasts(_pred(n=200, skill=0.1), "m", 24, 100, 1, 0.8)
    assert gate(s0, cfg, "hourly")["direction"]["verdict"] == INSUFFICIENT


def test_paired_difference_sign():
    d = _pred(skill=0.1)
    r = paired_brier_difference(d, "m", "clim", 24, 300, 2)
    assert r["mean_diff"] > 0 and r["ci"][0] > 0


def test_holm():
    out = holm({"a": 0.001, "b": 0.02, "c": 0.06}, 0.05)
    assert out["a"]["reject"] and np.isclose(out["a"]["p_holm"], 0.003)
    assert out["b"]["reject"] and np.isclose(out["b"]["p_holm"], 0.04)
    assert not out["c"]["reject"] and np.isclose(out["c"]["p_holm"], 0.06)
    # Step-down stops at the first non-rejection even if a later raw p is small enough.
    out = holm({"a": 0.03, "b": 0.03}, 0.05)
    assert not out["a"]["reject"] and not out["b"]["reject"]


def test_corr_test_detects_relationship():
    rng = np.random.default_rng(3)
    x = pd.Series(rng.normal(size=400))
    y = pd.Series(-0.5 * x + rng.normal(size=400))
    r = corr_test(x, y, 4, 300, 1)
    assert r["rho"] < -0.3 and r["ci"][1] < 0 and r["p"] < 0.01


def test_walk_forward_training_targets_resolve_before_test(monkeypatch):
    cfg = load_config()
    n = 900
    idx = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(5)
    df = pd.DataFrame({"tau": idx + pd.Timedelta(hours=1), "x": rng.normal(size=n), "vol": 0.01}, index=idx)
    df["y_4"] = rng.normal(0, 0.01, n)
    df["y_4_valid"] = True
    df["y_4_end"] = df["tau"] + pd.Timedelta(hours=4)
    seen = []
    real = wf.fit_predict_clim

    def spy(train, test, *a, **k):
        seen.append((train["y_4_end"].max(), test["tau"].min(), test.index.min(), train.index.max()))
        return real(train, test, *a, **k)

    monkeypatch.setattr(wf, "fit_predict_clim", spy)
    spec = wf.Spec("4h", "y_4", "y_4_valid", "y_4_end", 4, "vol", 300, 100, {"lin": ["x"]})
    pred, _ = wf.walk_forward(df, spec, cfg)
    assert len(seen) == 6
    for train_end, test_start, test_first, train_last in seen:
        assert train_end <= test_start
        assert train_last < test_first
    assert pred.index.is_unique and pred.index.is_monotonic_increasing


@pytest.mark.parametrize("h", ["1h", "4h", "next_session"])
def test_real_validation_evidence_is_consistent(h):
    from efie.validation.run import load_validation

    v = load_validation()
    if v is None:
        pytest.skip("validation not run")
    s = v["horizons"][h]["scores"]["tech_fund"]
    assert s["bss_ci"][0] <= s["bss"] <= s["bss_ci"][1]
    assert 0 <= s["coverage"] <= 1


def test_hypotheses_handle_two_weeks_published_together(synthetic_md):
    """EIA sometimes publishes two delayed weeks at the same moment; both must be kept."""
    import copy
    from dataclasses import replace

    from efie.validation.hypotheses import run_hypotheses

    ev = synthetic_md.events
    crude = ev[ev["series"] == "eia_crude"]
    late = crude.iloc[[5]].copy()
    late["event_id"] = "catch-up"
    late["reference_date"] = late["reference_date"] - pd.Timedelta(days=7)
    late["release_ts"] = crude.iloc[6]["release_ts"]  # published alongside the next week
    md2 = replace(synthetic_md, events=pd.concat([ev, late], ignore_index=True))
    cfg = copy.deepcopy(load_config())
    cfg["validation"]["bootstrap_reps"] = 50
    res = run_hypotheses(md2, cfg)
    assert res["family"]["H1_eia_surprise_drift_1h"]["n"] > 0


def test_interval_gate_prefers_climatology_when_model_interval_is_worse():
    cfg = load_config()
    d = _pred(skill=0.1)
    d["lo_m"], d["hi_m"] = -2.5, 2.5  # over-wide: covered but worse than climatology
    s = score_forecasts(d, "m", 24, 200, 1, 0.8)
    assert s["interval_score"] > s["interval_score_clim"]
    g = gate(s, cfg, "hourly")
    assert g["interval"]["verdict"] == FAIL
