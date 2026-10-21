"""Row files for the hosted EFIE dashboard.

The hosted dashboard reads prices live from the reader's own TradingView connection;
what only the engine knows — forecasts behind the gate, releases against consensus, the
release schedule, theses, what changed, and the validation and backtest evidence — it
reads from these JSON files (arrays of row objects), written from the latest reports and
evidence. Values are rounded for display here, not in the page.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from efie.features.build import MarketData
from efie.market.sessions import ET
from efie.paths import DASHBOARD_DIR, EVIDENCE_DIR, REPORTS_DIR
from efie.reports.pine_schedule import USUAL, parse, schedule_string

OUT = DASHBOARD_DIR / "data"
LABELS = {
    "eia_crude": "EIA crude stocks",
    "eia_gasoline": "EIA gasoline stocks",
    "eia_distillate": "EIA distillate stocks",
    "eia_cushing": "EIA Cushing stocks",
    "eia_runs": "EIA refinery crude runs",
    "eia_imports": "EIA crude imports",
    "api_crude": "API crude stocks",
    "bh_oil_rigs": "Baker Hughes oil rigs",
}


def _load(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def _r(x, n=4):
    return None if x is None else round(float(x), n)


def _m(x):
    """Barrels → million barrels (rig counts stay as they are)."""
    return None if x is None else round(float(x) / 1e6, 3)


def build_rows(md: MarketData) -> dict[str, list[dict]]:
    hourly = _load(REPORTS_DIR / "hourly" / "latest.json") or {}
    daily = _load(REPORTS_DIR / "daily" / "latest.json") or {}
    val = _load(EVIDENCE_DIR / "validation.json") or {}
    bt = _load(EVIDENCE_DIR / "backtest.json") or {}
    rows: dict[str, list[dict]] = {}

    fc = []
    for rep in (hourly, daily):
        for f in rep.get("forecasts", []):
            s, g = f["shown"], f["gate"]["components"]
            fc.append(
                {
                    "horizon": {"1h": "1 hour", "4h": "4 hours", "next_session": "Next session"}[f["horizon"]],
                    "p_up": _r(s["p_up"], 3),
                    "p_up_source": s["p_up_source"],
                    "expected_return": _r(s["expected_return"], 5),
                    "range_low": _r(s["interval_prices"][0], 2),
                    "range_high": _r(s["interval_prices"][1], 2),
                    "range_coverage": s["interval_nominal"],
                    "range_source": s["interval_source"],
                    "direction_gate": g.get("direction", {}).get("verdict"),
                    "return_gate": g.get("expected_return", {}).get("verdict"),
                    "range_gate": g.get("interval", {}).get("verdict"),
                    "direction_reason": g.get("direction", {}).get("reason"),
                    "as_of_et": str(pd.Timestamp(f["decision_ts"]).tz_convert(ET).strftime("%a %d %b %H:%M")),
                }
            )
    rows["efie_forecasts"] = fc

    rel = []
    # The hourly report is the most recent, so it carries a release the daily one predates.
    for s, x in (hourly.get("fundamentals", {}).get("latest") or daily.get("fundamentals", {}).get("latest") or {}).items():
        rig = s == "bh_oil_rigs"
        rel.append(
            {
                "series": LABELS.get(s, s),
                "released_et": pd.Timestamp(x["release_ts"]).tz_convert(ET).strftime("%a %d %b %H:%M"),
                "period": x["period"],
                "unit": "rigs" if rig else ("M bbl/d" if s in ("eia_runs", "eia_imports") else "M bbl"),
                "actual": x["actual"] if rig else _m(x["actual"]),
                "consensus": None if rig else _m(x["consensus"]),
                "surprise": None if rig else _m(x["surprise"]),
                "surprise_z": _r(x["surprise_z"], 2),
                "vs_5yr_week": None if rig else _m(x["seasonal_dev"]),
            }
        )
    rows["efie_releases"] = rel

    sched = schedule_string(md)
    p = parse(sched)
    up = []
    for k, label in (("E", "EIA weekly petroleum report"), ("A", "API weekly statistics")):
        for t in sorted(p[k]):
            ts = pd.Timestamp(t, unit="ms", tz="UTC").tz_convert(ET)
            if ts <= md.snapshot:
                continue
            dow, hhmm = USUAL[k]
            note = "holiday-week shift" if ts.dayofweek != dow else ("unusual time — check nearer the date" if f"{ts:%H:%M}" != hhmm else "")
            cons = md.events[(md.events["series"] == ("eia_crude" if k == "E" else "api_crude")) & (md.events["release_ts"] == ts.tz_convert("UTC"))]["consensus"]
            up.append({"release": label, "when_et": f"{ts:%a %d %b %H:%M}", "sort_key": int(t), "crude_consensus": _m(cons.iloc[0]) if len(cons) and pd.notna(cons.iloc[0]) else None, "note": note})
    rows["efie_schedule"] = sorted(up, key=lambda r: r["sort_key"])
    rows["efie_pine_schedule"] = [{"schedule": sched, "releases": len(p["E"]) + len(p["A"])}]

    ev = md.events[(md.events["series"] == "eia_crude") & md.events["actual"].notna() & md.events["consensus"].notna()].tail(26)
    rows["efie_surprises"] = [
        {"week": r["period"], "released": str(r["release_ts"].tz_convert(ET).date()), "surprise": _m(r["actual"] - r["consensus"])} for _, r in ev.iterrows()
    ]

    th = []
    for t in (hourly or daily).get("theses", []):
        th.append(
            {
                "id": t["id"],
                "thesis": t["title"],
                "status": t["status"],
                "label": t["label"],
                "claim": t["claim"],
                "implies": t["lean"],
                "strengthens": "; ".join(f"{o['label']} {o.get('display', '')}" for o in t["observations"] if o["state"] == "strengthens") or "none",
                "invalidates": "; ".join(f"{o['label']} {o.get('display', '')}" for o in t["observations"] if o["state"] == "invalidates") or "none",
                "missing": "; ".join(o["label"] for o in t["observations"] if o["state"] == "missing") or "none",
                "history": "; ".join(
                    f"{e['id'].split('_', 1)[0]} ρ {e['rho']:+.3f} (n={e['n']}, {'significant' if e['significant_after_holm'] else 'not significant'})" for e in t["evidence"]
                ),
            }
        )
    rows["efie_theses"] = th

    notes = [{"kind": "What changed in the last hour", "text": c} for c in hourly.get("changes", [])]
    notes += [{"kind": "How the indicators fit together", "text": c} for c in (hourly or daily).get("interpretations", [])]
    rows["efie_notes"] = [dict(n, n=i) for i, n in enumerate(notes)]

    vrows = []
    for h, r in (val.get("horizons") or {}).items():
        for m in ("tech", "tech_fund"):
            s, g = r["scores"][m], r["gate"][m]
            vrows.append(
                {
                    "horizon": {"1h": "1 hour", "4h": "4 hours", "next_session": "Next session"}[h],
                    "model": {"tech": "Technical only", "tech_fund": "EFIE (technical + fundamentals)"}[m],
                    "forecasts": s["n"],
                    "brier_skill": _r(s["bss"], 4),
                    "brier_skill_low": _r(s["bss_ci"][0], 4),
                    "brier_skill_high": _r(s["bss_ci"][1], 4),
                    "coverage": _r(s["coverage"], 3),
                    "validated": all(g[k]["verdict"] == "VALIDATED" for k in ("direction",)),
                }
            )
    rows["efie_validation"] = vrows

    orow = []
    for k, t in (bt.get("tests") or {}).items():
        base, overlay = k.split(" :: ")
        orow.append(
            {
                "test": k,
                "baseline": base.replace("REF ", "Reference "),
                "overlay": {"eia_standaside": "Stand aside around EIA", "efie_agreement": "Trade only when EFIE agrees", "carry_filter": "Carry filter"}.get(overlay, overlay),
                "usd_per_session": _r(t["mean_diff_usd_per_session"], 2),
                "usd_low": _r(t["ci"][0], 2),
                "usd_high": _r(t["ci"][1], 2),
                "sharpe_change": _r(t["sharpe_diff"], 2),
                "p_holm": _r(t["p_holm"], 3),
                "significant": bool(t["significant_after_holm"]),
            }
        )
    rows["efie_overlays"] = orow

    rows["efie_freshness"] = [
        {"source": x["source"], "last": x["last"][:16], "status": x["status"]} for x in (hourly or daily).get("freshness", [])
    ]
    m = hourly.get("market", {})
    rows["efie_status"] = [
        {
            "as_of_et": pd.Timestamp(hourly.get("asof", str(md.snapshot))).tz_convert(ET).strftime("%a %d %b %H:%M ET"),
            "curve": m.get("regime"),
            "spread_z_240h": _r(m.get("spread12_z"), 2),
            "crack_z_250d": _r(m.get("crack321_z"), 2),
            "models_validated": sum(1 for r in fc if r["direction_gate"] == "VALIDATED"),
            "horizons": len(fc),
        }
    ]
    return rows


def write_rows(md: MarketData) -> dict[str, str]:
    OUT.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, r in build_rows(md).items():
        p = OUT / f"{name}.json"
        p.write_text(json.dumps(r, indent=1, default=str))
        written[name] = str(p)
    (OUT / "_written_at.txt").write_text(datetime.now(timezone.utc).isoformat(timespec="seconds") + "\n")
    return written
