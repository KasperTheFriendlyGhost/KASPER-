"""Data-integrity diagnostics: coverage, roll reconstruction, release-time alignment."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from efie.features.build import MarketData
from efie.ingest.stage import read_manifest
from efie.paths import EVIDENCE_DIR


def coverage(md: MarketData) -> list[dict]:
    rows = []
    for k, v in md.hourly.items():
        if len(v):
            rows.append({"series": k, "interval": "1h", "rows": int(len(v)), "first": str(v.index[0]), "last": str(v.index[-1])})
    for k, v in md.daily.items():
        if len(v):
            rows.append({"series": k, "interval": "1D", "rows": int(len(v)), "first": str(v.index[0].date()), "last": str(v.index[-1].date())})
    ev = md.events[md.events["actual"].notna()]
    for s, g in ev.groupby("series"):
        rows.append(
            {
                "series": s,
                "interval": "release",
                "rows": int(len(g)),
                "with_consensus": int(g["consensus"].notna().sum()),
                "first": str(g["release_ts"].min()),
                "last": str(g["release_ts"].max()),
            }
        )
    return rows


def missing_release_weeks(md: MarketData, series: str = "eia_crude", start: str = "2015-01-05") -> dict:
    ev = md.events[(md.events["series"] == series) & md.events["actual"].notna()]
    wk = ev["release_ts"].dt.isocalendar()
    have = set(zip(wk["year"].astype(int), wk["week"].astype(int)))
    d = pd.Timestamp(start)
    missing, doubled = [], []
    counts = pd.Series(list(zip(wk["year"].astype(int), wk["week"].astype(int)))).value_counts()
    while d < ev["release_ts"].max().tz_convert(None):
        k = (d.isocalendar()[0], d.isocalendar()[1])
        if k not in have:
            missing.append(str(d.date()))
        elif counts.get(k, 0) > 1:
            doubled.append(str(d.date()))
        d += pd.Timedelta(days=7)
    return {"missing_weeks": missing, "weeks_with_two_releases": doubled}


def release_alignment(md: MarketData, series: str = "eia_crude") -> dict:
    """Median |return| and relative volume of hourly bars around the stated release bar."""
    h = md.hourly["CL1"]
    r = np.log(h["c"]).diff()
    v = h["v"]
    ev = md.events[(md.events["series"] == series) & (md.events["release_ts"] >= h.index[0]) & md.events["actual"].notna()]
    rows = []
    for t in ev["release_ts"]:
        i = h.index.searchsorted(t, side="right") - 1
        if i < 6 or i + 4 >= len(h):
            continue
        base = v.iloc[i - 6 : i - 2].mean()
        for k in range(-3, 4):
            rows.append((k, abs(r.iloc[i + k]), v.iloc[i + k] / base if base > 0 else np.nan))
    if not rows:
        return {}
    x = pd.DataFrame(rows, columns=["offset_bars", "abs_ret", "rel_volume"]).groupby("offset_bars").median()
    et = ev["release_ts"].dt.tz_convert("America/New_York")
    return {
        "n_releases": int(len(ev)),
        "release_times_et": et.dt.strftime("%a %H:%M").value_counts().to_dict(),
        "profile": x.reset_index().to_dict(orient="records"),
    }


def roll_summary(cal: pd.DataFrame) -> dict:
    return {
        "contracts": int(len(cal)),
        "by_method": cal["method"].value_counts().to_dict(),
        "detected_offset_bd": cal.loc[cal["method"] != "calendar_default", "offset_bd"].value_counts().sort_index().to_dict(),
        "recent": cal.tail(6)[["contract", "last_trade_date", "roll_trading_date", "offset_bd", "method", "spread_before"]].astype(str).to_dict(orient="records"),
    }


def run_diagnostics(md: MarketData, write: bool = True) -> dict:
    agree = md.roll_d.merge(md.roll_h, on="contract", suffixes=("_d", "_h"))
    out = {
        "snapshot": str(md.snapshot),
        "manifest_files": len(read_manifest()),
        "coverage": coverage(md),
        "eia_weeks": missing_release_weeks(md),
        "release_alignment_hourly": release_alignment(md),
        "rolls_hourly": roll_summary(md.roll_h),
        "rolls_daily": roll_summary(md.roll_d),
        "rolls_daily_vs_hourly_same_date": f"{int((agree['roll_trading_date_d'] == agree['roll_trading_date_h']).sum())}/{len(agree)}",
    }
    if write:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        (EVIDENCE_DIR / "diagnostics.json").write_text(json.dumps(out, indent=2, default=str))
    return out
