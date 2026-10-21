"""Hourly and daily EFIE reports, reproducible as of any past moment.

``make_report(kind, md, asof)`` rebuilds everything from what was knowable at ``asof``:
bars that had closed, sessions that had settled, releases that had been published. The
validation gate is recomputed from the out-of-sample forecasts made before ``asof``, so
a replayed report shows what the gate said *then*. Future release *schedules* are shown
(they are published in advance); future values never are.
"""

from __future__ import annotations

import json
from datetime import timedelta

import numpy as np
import pandas as pd

from efie.config import load_config
from efie.explain.theses import evaluate, interpretations
from efie.features.catalysts import known_at
from efie.features.build import MarketData, build_daily, build_hourly, truncate
from efie.features.inventories import release_features
from efie.market.sessions import ET
from efie.paths import EVIDENCE_DIR, PROCESSED_DIR, REPORTS_DIR
from efie.validation.gate import FAIL, INSUFFICIENT, PASS, gate
from efie.validation.metrics import score_forecasts
from efie.validation.run import specs
from efie.validation.walkforward import fit_latest

DISCLAIMER = (
    "Research output only. EFIE has no connection to the MCL Command Desk, the risk governor, "
    "HARD LOCK or any order path. Probabilities are shown as model forecasts only where the "
    "out-of-sample validation gate passed; otherwise the unconditional (climatology) value is shown."
)

RELEASE_SERIES = ["eia_crude", "eia_gasoline", "eia_distillate", "eia_cushing", "eia_runs", "eia_imports", "api_crude", "bh_oil_rigs"]


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _load_json(name: str) -> dict | None:
    p = EVIDENCE_DIR / name
    return json.loads(p.read_text()) if p.exists() else None


def _gate_asof(horizon: str, asof: pd.Timestamp, cfg: dict, freq: str) -> dict:
    p = PROCESSED_DIR / f"oos_predictions_{horizon}.csv.gz"
    if not p.exists():
        return {"status": "validation not run", "components": {}}
    pred = pd.read_csv(p, index_col=0)
    pred["tau"] = pd.to_datetime(pred["tau"], utc=True)
    pred = pred[pred["tau"] <= asof]
    pred = pred[pred["y"].notna()]
    v = cfg["validation"]
    if len(pred) < 50:
        return {"status": INSUFFICIENT, "n_oos": int(len(pred)), "components": {k: {"verdict": INSUFFICIENT, "reason": "too few forecasts before this time"} for k in ("direction", "expected_return", "interval")}}
    block = v["block_len_hourly"] if freq == "hourly" else v["block_len_daily"]
    s = score_forecasts(pred, "tech_fund", block, min(v["bootstrap_reps"], 500), v["seed"], v["interval_nominal"])
    return {
        "status": "evaluated",
        "n_oos": s["n"],
        "score": {k: s[k] for k in ("bss", "bss_ci", "r2_oos", "r2_ci", "coverage", "coverage_clim", "calibration_gap", "interval_score", "interval_score_clim")},
        "components": gate(s, cfg, freq),
    }


def _forecasts(df: pd.DataFrame, spec, cfg: dict, freq: str, asof: pd.Timestamp, close: float) -> dict:
    row = df.iloc[[-1]]
    fc = fit_latest(df, spec, cfg, row["tau"].iloc[0], row)
    g = _gate_asof(spec.name, asof, cfg, freq)
    comp = g["components"]
    mult = cfg["instrument"]["multiplier_bbl"]

    def pick(component: str, model_val, clim_val):
        ok = comp.get(component, {}).get("verdict") == PASS
        return (model_val if ok else clim_val), ("model" if ok else "climatology")

    p, p_src = pick("direction", fc["p_tech_fund"].iloc[0], fc["p_clim"].iloc[0])
    mu, mu_src = pick("expected_return", fc["mu_tech_fund"].iloc[0], fc["mu_clim"].iloc[0])
    lo, lo_src = pick("interval", fc["lo_tech_fund"].iloc[0], fc["lo_clim"].iloc[0])
    hi, _ = pick("interval", fc["hi_tech_fund"].iloc[0], fc["hi_clim"].iloc[0])
    return {
        "horizon": spec.name,
        "decision_ts": str(row["tau"].iloc[0]),
        "n_train": int(fc["n_train"].iloc[0]),
        "shown": {
            "p_up": _f(p),
            "p_up_source": p_src,
            "expected_return": _f(mu),
            "expected_return_source": mu_src,
            "expected_usd_per_mcl": _f(mu * close * mult),
            "interval": [_f(lo), _f(hi)],
            "interval_prices": [_f(close * np.exp(lo)), _f(close * np.exp(hi))],
            "interval_source": lo_src,
            "interval_nominal": cfg["validation"]["interval_nominal"],
        },
        "efie_model_raw": {"p_up": _f(fc["p_tech_fund"].iloc[0]), "expected_return": _f(fc["mu_tech_fund"].iloc[0])},
        "climatology": {"p_up": _f(fc["p_clim"].iloc[0]), "expected_return": _f(fc["mu_clim"].iloc[0])},
        "gate": g,
    }


def _latest_releases(md: MarketData, cfg: dict, asof: pd.Timestamp) -> dict:
    if md.events.empty:
        return {}
    feat = release_features(md.events, cfg["point_in_time"]["release_buffer_minutes"])
    feat = feat[feat["available_ts"] <= asof]
    out = {}
    for s in RELEASE_SERIES:
        g = feat[feat["series"] == s]
        if g.empty:
            continue
        r = g.iloc[-1]
        out[s] = {
            "release_ts": str(r["release_ts"]),
            "period": r.get("period"),
            "actual": _f(r["actual"]),
            "consensus": _f(r["consensus"]),
            "surprise": _f(r.get("surprise")),
            "surprise_z": _f(r.get("surprise_z")),
            "change_z": _f(r.get("change_z")),
            "seasonal_dev": _f(r.get("seasonal_dev")),
            "previous_as_reported": _f(r["previous"]),
            "age_hours": _f((asof - r["available_ts"]).total_seconds() / 3600),
        }
        if len(g) >= 2:
            out[s]["prior_release_actual"] = _f(g.iloc[-2]["actual"])
    return out


def _next_scheduled(md_full: MarketData, asof: pd.Timestamp) -> list[dict]:
    ev = md_full.events
    fut = ev[(ev["release_ts"] > asof) & ev["series"].isin(["eia_crude", "api_crude", "bh_oil_rigs"])].sort_values("release_ts")
    rows = []
    for s in ("api_crude", "eia_crude", "bh_oil_rigs"):
        g = fut[fut["series"] == s]
        if len(g):
            r = g.iloc[0]
            rows.append({"series": s, "release_ts": str(r["release_ts"]), "release_et": str(r["release_ts"].tz_convert(ET)), "consensus": _f(r["consensus"])})
    return rows


def _freshness(md: MarketData, asof: pd.Timestamp) -> list[dict]:
    rows = []
    for k, v in md.hourly.items():
        if len(v):
            last = v.index[-1] + timedelta(hours=1)
            rows.append({"source": f"{k} hourly", "last": str(last), "age_hours": _f((asof - last).total_seconds() / 3600)})
    for k, v in md.daily.items():
        if len(v):
            rows.append({"source": f"{k} daily", "last": str(v.index[-1].date()), "age_hours": _f((asof - pd.Timestamp(v.index[-1]).tz_localize("UTC")).total_seconds() / 3600 - 24)})
    if not md.events.empty:
        pub = md.events[md.events["actual"].notna()]
        rows.append({"source": "economic calendar", "last": str(pub["release_ts"].max()), "age_hours": _f((asof - pub["release_ts"].max()).total_seconds() / 3600)})
    for r in rows:
        # Futures trade ~23h a day; the ETF and daily/weekly sources do not.
        limit = 24 * 4 if ("daily" in r["source"] or "calendar" in r["source"] or r["source"].startswith("BWET")) else 6
        r["status"] = "OK" if (r["age_hours"] is not None and r["age_hours"] <= limit) else "STALE"
    return rows


def _market(h: pd.DataFrame, d: pd.DataFrame) -> dict:
    hr, dr = h.iloc[-1], d.iloc[-1]
    def chg(n):
        return _f(h["r"].iloc[-n:].sum()) if len(h) >= n else None
    return {
        "cl1_last": _f(hr["close"]),
        "cl1_bar": str(h.index[-1]),
        "ret_1h": chg(1),
        "ret_4h": chg(4),
        "ret_24h": chg(24),
        "cl1_settle": _f(dr["close"]),
        "settle_date": str(d.index[-1].date()),
        "ret_1d": _f(dr["r"]),
        "ret_5d": _f(d["r"].iloc[-5:].sum()),
        "spread12": _f(hr["ts_spread12"]),
        "spread12_z": _f(hr["ts_spread12_z"]),
        "spread12_chg5": _f(dr["ts_spread12_chg5"]),
        "crack321": _f(hr["crk_321"]),
        "crack321_z": _f(dr["crk_321_z"]),
        "crack_diesel": _f(hr["crk_diesel"]),
        "crack_gas": _f(hr["crk_gas"]),
        "brent_wti": _f(dr["arb_brent_wti"]),
        "brent_wti_chg5": _f(dr["arb_brent_wti_chg5"]),
        "td3c": _f(dr.get("frt_td3c_level")),
        "td3c_age_days": _f(dr.get("frt_td3c_age_days")),
        "td3c_chg5": _f(dr.get("frt_td3c_chg5")),
        "bwet_chg5": _f(dr.get("frt_bwet_chg5")),
        "vol_24h_annualised": _f(hr["tech_vol_24"] * np.sqrt(252 * 23)),
        "regime": "backwardation" if hr["ts_spread12"] > 0 else "contango",
    }


def make_report(kind: str, md_full: MarketData, asof: pd.Timestamp | None = None, cfg: dict | None = None, with_changes: bool = True) -> dict:
    cfg = cfg or load_config()
    asof = pd.Timestamp(asof) if asof is not None else md_full.snapshot
    asof = asof.tz_localize("UTC") if asof.tzinfo is None else asof.tz_convert("UTC")
    md = truncate(md_full, asof)
    h, d = build_hourly(md, cfg), build_daily(md, cfg)
    spec_list = {s.name: (s, df, fr) for s, df, fr in specs(h, d, cfg)}
    horizons = ["1h", "4h"] if kind == "hourly" else ["next_session"]
    forecasts = []
    for name in horizons:
        spec, df, fr = spec_list[name]
        close = float(df["close"].iloc[-1])
        forecasts.append(_forecasts(df, spec, cfg, fr, asof, close))
    row = d.iloc[-1].to_dict()
    hrow = h.iloc[-1].to_dict()
    for k, val in hrow.items():
        if k.startswith("inv_") or k in ("ts_spread12",):
            row[k] = val
    hyp = _load_json("hypotheses.json")
    rep = {
        "kind": kind,
        "asof": str(asof),
        "asof_et": str(asof.tz_convert(ET)),
        "snapshot": str(md_full.snapshot),
        "market": _market(h, d),
        "fundamentals": {"latest": _latest_releases(md, cfg, asof), "next_scheduled": _next_scheduled(md_full, asof)},
        "forecasts": forecasts,
        "theses": evaluate(row, hyp),
        "interpretations": interpretations(row),
        "freshness": _freshness(md, asof),
        "catalysts": [
            {k: (str(v) if k.endswith("_utc") else v) for k, v in r.items()} for r in known_at(asof).to_dict(orient="records")
        ],
        "disclaimer": DISCLAIMER,
    }
    if with_changes:
        prev_asof = asof - pd.Timedelta(hours=1) if kind == "hourly" else _previous_session_close(d, asof)
        if prev_asof is not None:
            prev = make_report(kind, md_full, prev_asof, cfg, with_changes=False)
            rep["previous_asof"] = prev["asof"]
            rep["changes"] = diff_reports(prev, rep)
    return rep


def _previous_session_close(d: pd.DataFrame, asof: pd.Timestamp) -> pd.Timestamp | None:
    taus = pd.DatetimeIndex(d["tau"])
    earlier = taus[taus < asof - pd.Timedelta(minutes=1)]
    if len(earlier) < 2:
        return None
    return earlier[-2] if earlier[-1] >= asof - pd.Timedelta(hours=1) else earlier[-1]


def diff_reports(prev: dict, cur: dict) -> list[str]:
    """What changed between two reports, in plain language."""
    out = []
    pm, cm = prev["market"], cur["market"]
    for key, label, fmt in (
        ("cl1_last", "CL1 last", "{:.2f}"),
        ("spread12", "M1–M2 spread", "{:+.2f}"),
        ("crack321", "3-2-1 crack", "{:.2f}"),
        ("brent_wti", "Brent–WTI", "{:+.2f}"),
    ):
        a, b = pm.get(key), cm.get(key)
        if a is not None and b is not None and abs(b - a) > 1e-9:
            out.append(f"{label}: {fmt.format(a)} → {fmt.format(b)} ({b - a:+.2f})")
    if pm.get("regime") != cm.get("regime"):
        out.append(f"Curve regime changed: {pm.get('regime')} → {cm.get('regime')}")
    pf, cf = prev["fundamentals"]["latest"], cur["fundamentals"]["latest"]
    for s, rel in cf.items():
        if s not in pf or pf[s]["release_ts"] != rel["release_ts"]:
            val = rel["actual"]
            cons = rel["consensus"]
            txt = f"New {s.replace('_', ' ')} release ({rel['period']}): {val:,.0f}" if val is not None else f"New {s} release"
            if cons is not None and val is not None:
                txt += f" vs consensus {cons:,.0f} (surprise {val - cons:+,.0f}"
                txt += f", z {rel['surprise_z']:+.2f})" if rel.get("surprise_z") is not None else ")"
            if rel.get("previous_as_reported") is not None and pf.get(s, {}).get("actual") is not None:
                rev = rel["previous_as_reported"] - pf[s]["actual"]
                if abs(rev) > 1:
                    txt += f"; prior week revised by {rev:+,.0f}"
            out.append(txt)
    pt = {t["id"]: t["status"] for t in prev["theses"]}
    for t in cur["theses"]:
        if pt.get(t["id"]) != t["status"]:
            out.append(f"Thesis {t['id']} ({t['title']}): {pt.get(t['id'])} → {t['status']}")
    pfc = {f["horizon"]: f for f in prev["forecasts"]}
    for f in cur["forecasts"]:
        p = pfc.get(f["horizon"])
        if not p:
            continue
        for comp in ("direction", "expected_return", "interval"):
            a = p["gate"]["components"].get(comp, {}).get("verdict")
            b = f["gate"]["components"].get(comp, {}).get("verdict")
            if a != b:
                out.append(f"{f['horizon']} {comp} gate: {a} → {b}")
        a, b = p["shown"]["p_up"], f["shown"]["p_up"]
        if a is not None and b is not None and abs(a - b) >= 0.01:
            out.append(f"{f['horizon']} P(up) shown: {a:.3f} → {b:.3f} ({f['shown']['p_up_source']})")
    for fr in cur["freshness"]:
        pfr = next((x for x in prev["freshness"] if x["source"] == fr["source"]), None)
        if pfr and pfr["status"] != fr["status"]:
            out.append(f"Data {fr['source']}: {pfr['status']} → {fr['status']}")
    return out or ["No material change."]


def write_report(rep: dict) -> tuple[str, str]:
    from efie.reports.render import to_markdown

    kind = rep["kind"]
    d = REPORTS_DIR / kind
    d.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp(rep["asof"]).strftime("%Y%m%dT%H%MZ")
    j = d / f"EFIE_{kind}_{stamp}.json"
    m = d / f"EFIE_{kind}_{stamp}.md"
    j.write_text(json.dumps(rep, indent=2, default=str))
    m.write_text(to_markdown(rep))
    (d / "latest.json").write_text(json.dumps(rep, indent=2, default=str))
    (d / "latest.md").write_text(to_markdown(rep))
    return str(j), str(m)
