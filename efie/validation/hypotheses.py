"""Pre-registered event studies and predictive-relationship tests.

These are written down before they are run (see ``docs/HYPOTHESES.md``). Each test is
a rank correlation between a quantity known at decision time and an outcome that
resolves strictly afterwards, with a moving-block bootstrap CI and an approximate
two-sided bootstrap p-value. The tradeable family is Holm–Bonferroni adjusted; the
sanity checks (reactions *inside* the release bar, which cannot be traded) are not part
of the family — they exist to show the data and timestamps line up.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from efie.features.build import MarketData, build_daily, build_hourly, masked_diff
from efie.validation.metrics import bootstrap

H = pd.Timedelta(hours=1)


def _rho(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 5 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(spearmanr(x, y).statistic)


def corr_test(x: pd.Series, y: pd.Series, block: int, reps: int, seed: int) -> dict:
    d = pd.concat([x, y], axis=1).dropna()
    if len(d) < 20:
        return {"n": int(len(d)), "rho": float("nan"), "ci": [float("nan")] * 2, "p": float("nan")}
    a, b = d.iloc[:, 0].to_numpy(float), d.iloc[:, 1].to_numpy(float)
    rho = _rho(a, b)
    bs = bootstrap(_rho, (a, b), block, reps, seed)
    bs = bs[np.isfinite(bs)]
    p = float(min(1.0, 2 * min((bs <= 0).mean(), (bs >= 0).mean())))
    return {
        "n": int(len(d)),
        "rho": rho,
        "ci": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
        "p": p,
        "start": str(d.index[0]),
        "end": str(d.index[-1]),
    }


def holm(pvals: dict[str, float], alpha: float) -> dict[str, dict]:
    items = sorted(((k, p) for k, p in pvals.items() if np.isfinite(p)), key=lambda kv: kv[1])
    m = len(items)
    out, running, stop = {}, 0.0, False
    for i, (k, p) in enumerate(items):
        adj = min(1.0, (m - i) * p)
        running = max(running, adj)
        reject = (not stop) and running <= alpha
        stop = stop or not reject
        out[k] = {"p": p, "p_holm": running, "reject": reject}
    for k, p in pvals.items():
        out.setdefault(k, {"p": p, "p_holm": float("nan"), "reject": False})
    return out


def _release_bar_returns(h: pd.DataFrame, release_ts: pd.Series) -> pd.DataFrame:
    """For each release: return of the bar containing it, and drifts after that bar.

    The result is aligned to ``release_ts``'s index (one row per release, in order).
    """
    idx = h.index
    pos = idx.searchsorted(pd.DatetimeIndex(release_ts), side="right") - 1
    rows = []
    for rts, i in zip(release_ts, pos):
        if i < 0 or i + 4 >= len(idx) or not (idx[i] <= rts < idx[i] + H):
            rows.append((rts, np.nan, np.nan, np.nan))
            continue
        r = h["r"].to_numpy()
        rows.append((rts, r[i], r[i + 1], r[i + 1 : i + 5].sum() if h["y_4_valid"].iloc[i] else np.nan))
    return pd.DataFrame(rows, columns=["release_ts", "bar_ret", "drift_1h", "drift_4h"], index=release_ts.index)


def run_hypotheses(md: MarketData, cfg: dict) -> dict:
    v = cfg["validation"]
    reps, seed = v["bootstrap_reps"], v["seed"]
    h = build_hourly(md, cfg)
    d = build_daily(md, cfg)
    ev = md.events
    out: dict[str, dict] = {"sanity": {}, "family": {}}

    def rel(series: str) -> pd.DataFrame:
        from efie.features.inventories import release_features

        f = release_features(ev, cfg["point_in_time"]["release_buffer_minutes"])
        # One row per reference week. Two weeks can share a release time (EIA catch-up
        # after a delay), so the release time is a column, not the key.
        g = f[f["series"] == series].drop_duplicates(subset="reference_date", keep="last")
        return g.set_index("reference_date")

    eia = rel("eia_crude")
    api = rel("api_crude")
    cush = rel("eia_cushing")

    # --- sanity: reactions inside the release bar / release session (not tradeable)
    rb = _release_bar_returns(h, eia["release_ts"])
    out["sanity"]["S1_eia_surprise_vs_release_bar_return"] = {
        "question": "Does the hourly bar containing the EIA release move against the crude surprise?",
        "expected_sign": -1,
        **corr_test(eia["surprise_z"], rb["bar_ret"], 4, reps, seed),
    }
    rb_api = _release_bar_returns(h, api["release_ts"])
    out["sanity"]["S2_api_change_vs_release_bar_return"] = {
        "question": "Does the hourly bar containing the API release move against the API crude change?",
        "expected_sign": -1,
        **corr_test(api["change_z"], rb_api["bar_ret"], 4, reps, seed + 1),
    }
    # Daily: release-day session return (open→settle) — the release falls inside it.
    day_of = pd.DatetimeIndex([pd.Timestamp(t.tz_convert("America/New_York").date()) for t in eia["release_ts"]])
    intraday = np.log(d["close"] / d["open"])
    sess = pd.Series(intraday.reindex(day_of).to_numpy(), index=eia.index)
    out["sanity"]["S3_eia_surprise_vs_release_day_session"] = {
        "question": "Does the release-day session (open→settle) move against the crude surprise?",
        "expected_sign": -1,
        **corr_test(eia["surprise_z"], sess, 4, reps, seed + 2),
    }
    # Added after the first run (diagnostics, not part of the tradeable family): the API
    # report lands in the overnight gap before the EIA session, so measure settle→settle,
    # and the EIA surprise relative to the API figure.
    cc = pd.Series(d["r"].reindex(day_of).to_numpy(), index=eia.index)
    out["sanity"]["S4_eia_surprise_vs_settle_to_settle"] = {
        "question": "Prior settlement → release-day settlement (includes the API reaction the evening before).",
        "expected_sign": -1,
        "post_hoc": True,
        **corr_test(eia["surprise_z"], cc, 4, reps, seed + 13),
    }
    from efie.features.inventories import eia_minus_api, release_features as _rf

    em = eia_minus_api(_rf(ev, cfg["point_in_time"]["release_buffer_minutes"]))
    em = em.drop_duplicates(subset="reference_date", keep="last").set_index("reference_date")
    out["sanity"]["S5_eia_minus_api_vs_release_day_session"] = {
        "question": "Does the EIA figure's deviation from the API figure move the release-day session against it?",
        "expected_sign": -1,
        "post_hoc": True,
        **corr_test(em["eia_minus_api_z"], sess.reindex(em.index), 4, reps, seed + 14),
    }

    fam = out["family"]
    # --- post-release drift (decision after the release bar closes)
    fam["H1_eia_surprise_drift_1h"] = {
        "question": "After the release bar closes, does the next hour continue (or reverse) the surprise?",
        **corr_test(eia["surprise_z"], rb["drift_1h"], 4, reps, seed + 3),
    }
    fam["H2_eia_surprise_drift_4h"] = {
        "question": "Same, over the next four hours.",
        **corr_test(eia["surprise_z"], rb["drift_4h"], 4, reps, seed + 4),
    }
    nxt = pd.Series(d["y_next"].reindex(day_of).to_numpy(), index=eia.index)
    fam["H3_eia_surprise_next_session"] = {
        "question": "Does the crude surprise predict the next session (open→settle) after release day?",
        **corr_test(eia["surprise_z"], nxt, 4, reps, seed + 5),
    }
    # --- API → EIA
    a = api[["release_ts", "surprise_z", "change_z"]].reset_index()
    e = eia[["release_ts", "surprise_z"]].reset_index()
    m = a.merge(e, on="reference_date", suffixes=("_api", "_eia")).set_index("reference_date")
    fam["H4_api_surprise_predicts_eia_surprise"] = {
        "question": "Does the API surprise (Tuesday) predict the EIA surprise (Wednesday)?",
        **corr_test(m["surprise_z_api"], m["surprise_z_eia"], 4, reps, seed + 6),
    }
    # API bar close → bar before EIA release.
    drift = []
    for _, row in m.iterrows():
        t_api, t_eia = row["release_ts_api"], row["release_ts_eia"]
        i0 = h.index.searchsorted(t_api, side="right") - 1
        i1 = h.index.searchsorted(t_eia, side="right") - 1
        if i0 < 0 or i1 <= i0 + 1 or not (h.index[i0] <= t_api < h.index[i0] + H):
            drift.append(np.nan)
            continue
        drift.append(h["r"].iloc[i0 + 1 : i1].sum())
    m["api_to_eia_drift"] = drift
    fam["H5_api_change_drift_until_eia"] = {
        "question": "Does the API crude change predict the move from the API bar close to just before EIA?",
        **corr_test(m["change_z"], m["api_to_eia_drift"], 4, reps, seed + 7),
    }
    # --- Cushing → front spread over the next 5 sessions
    spr = d["ts_spread12"]
    fwd_spr = (masked_diff(spr, 5, d["roll"]).shift(-5)).rename("fwd")
    day_c = pd.DatetimeIndex([pd.Timestamp(t.tz_convert("America/New_York").date()) for t in cush["release_ts"]])
    fam["H6_cushing_change_vs_next5_spread_change"] = {
        "question": "Do Cushing builds (draws) precede a weaker (stronger) M1–M2 spread over 5 sessions?",
        **corr_test(cush["change_z"], pd.Series(fwd_spr.reindex(day_c).to_numpy(), index=cush.index), 4, reps, seed + 8),
    }
    # --- daily predictive relationships (overlapping info → block 10)
    fam["H7_crack321_chg5_vs_next_session"] = {
        "question": "Does 5-day 3-2-1 crack momentum predict the next WTI session?",
        **corr_test(d["crk_321_chg5"], d["y_next"], 10, reps, seed + 9),
    }
    fam["H8_spread12_pct_vs_next_session"] = {
        "question": "Does the M1–M2 spread (backwardation > 0) predict the next WTI session?",
        **corr_test(d["ts_spread12_pct"], d["y_next"], 10, reps, seed + 10),
    }
    fwd_arb = (d["arb_brent_wti"].shift(-5) - d["arb_brent_wti"]).rename("fwd_arb")
    fam["H9_td3c_chg5_vs_next5_brent_wti_change"] = {
        "question": "Does rising VLCC freight (TD3C) precede a wider Brent–WTI spread over 5 sessions?",
        **corr_test(d["frt_td3c_chg5"], fwd_arb, 10, reps, seed + 11),
    }
    fam["H10_td3c_chg5_vs_next_session"] = {
        "question": "Does 5-day VLCC freight momentum predict the next WTI session?",
        **corr_test(d["frt_td3c_chg5"], d["y_next"], 10, reps, seed + 12),
    }
    adj = holm({k: v_["p"] for k, v_ in fam.items()}, cfg["backtest"]["family_alpha"])
    for k in fam:
        fam[k].update({"p_holm": adj[k]["p_holm"], "significant_after_holm": adj[k]["reject"]})
    return out
