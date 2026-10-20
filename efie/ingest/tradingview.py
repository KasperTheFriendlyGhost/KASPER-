"""Parse staged TradingView connector results into tidy tables.

Two result types are handled:

* ``get_ohlcv`` — bars as rows ``[{t,o,h,l,c,v}]`` or columns ``{t:[...], ...}``;
  ``t`` is the bar's open time in Unix seconds (UTC).
* ``get_economic_calendar`` — ``{"result": [event, ...]}``.

Bars that were still forming when the result was fetched are dropped, using the
manifest's ``staged_at`` time as the snapshot time.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd

from efie.ingest.registry import CALENDAR_SERIES, SYMBOL_TO_SERIES
from efie.ingest.stage import read_manifest
from efie.market.sessions import daily_bar_close_utc, trading_date_from_daily_t
from efie.paths import RAW_DIR

INTERVAL_SECONDS = {"1h": 3600, "4h": 14400, "1D": 86400}


def bars_from_payload(payload: dict) -> pd.DataFrame:
    bars = payload["bars"]
    df = pd.DataFrame(bars)
    if df.empty:
        return pd.DataFrame(columns=["o", "h", "l", "c", "v"])
    df["t"] = pd.to_datetime(df["t"].astype("int64"), unit="s", utc=True)
    return df.set_index("t")[["o", "h", "l", "c", "v"]].astype(float).sort_index()


def _complete(df: pd.DataFrame, interval: str, snapshot: pd.Timestamp) -> pd.DataFrame:
    """Keep only bars whose close time is at or before the snapshot time."""
    if df.empty:
        return df
    if interval == "1D":
        closes = pd.DatetimeIndex([daily_bar_close_utc(t) for t in df.index])
    else:
        closes = df.index + timedelta(seconds=INTERVAL_SECONDS[interval])
    return df[closes <= snapshot]


def load_ohlcv(series: str, interval: str) -> pd.DataFrame:
    """All staged pages for one series/interval, merged, de-duplicated and completed."""
    frames = []
    for e in read_manifest():
        req = e["request"]
        if req.get("tool") != "get_ohlcv" or req.get("interval") != interval:
            continue
        if SYMBOL_TO_SERIES.get(req.get("symbol")) != series:
            continue
        payload = json.loads((RAW_DIR / e["file"]).read_text())
        if payload.get("symbol") != req["symbol"] or payload.get("interval") != interval:
            raise ValueError(f"{e['file']}: payload does not match its manifest request")
        snapshot = pd.Timestamp(e["staged_at"])
        frames.append((snapshot, _complete(bars_from_payload(payload), interval, snapshot)))
    frames += [(s, f) for s, f in _csv_frames(series, interval)]
    if not frames:
        return pd.DataFrame(columns=["o", "h", "l", "c", "v"])
    # Later snapshots win where pages overlap.
    frames.sort(key=lambda x: x[0])
    df = pd.concat([f for _, f in frames])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def _csv_frames(series: str, interval: str):
    from efie.ingest.csv_import import load_csv_frames

    return load_csv_frames(series, interval)


def daily_close_frame(series: str) -> pd.DataFrame:
    """Daily bars indexed by trading date (the session the bar belongs to)."""
    df = load_ohlcv(series, "1D")
    if df.empty:
        return df
    out = df.copy()
    out.index = pd.DatetimeIndex([trading_date_from_daily_t(t) for t in df.index], name="date")
    return out[~out.index.duplicated(keep="last")]


def load_calendar_events() -> pd.DataFrame:
    """Energy releases (EIA, API, Baker Hughes) from every staged calendar window."""
    seen: dict[str, dict] = {}
    for e in read_manifest():
        if e["request"].get("tool") != "get_economic_calendar":
            continue
        for ev in json.loads((RAW_DIR / e["file"]).read_text())["result"]:
            if ev.get("ticker") in CALENDAR_SERIES:
                seen[ev["id"]] = ev
    rows = []
    for ev in seen.values():
        meta = CALENDAR_SERIES[ev["ticker"]]
        rows.append(
            {
                "event_id": ev["id"],
                "series": meta["name"],
                "ticker": ev["ticker"],
                "title": ev.get("title"),
                "release_ts": pd.Timestamp(ev["date"]).tz_convert("UTC"),
                "reference_date": pd.Timestamp(ev["referenceDate"]).tz_convert("UTC") if ev.get("referenceDate") else pd.NaT,
                "period": ev.get("period"),
                "actual": ev.get("actualRaw"),
                "consensus": ev.get("forecastRaw"),
                "previous": ev.get("previousRaw"),
                "importance": ev.get("importance"),
                "source": ev.get("source"),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in ("actual", "consensus", "previous"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values(["series", "release_ts", "event_id"])
    # The same release can appear under two ids (title variants); keep one per series,
    # time and reference week. Two *different* weeks published at the same moment (EIA's
    # catch-up after a delayed report) are both kept.
    df["_ref"] = df["reference_date"].astype(str)
    df = df.drop_duplicates(subset=["series", "release_ts", "_ref"], keep="last").drop(columns="_ref")
    # Revision seen at the next release: its "previous" vs this release's first print.
    df["next_previous"] = df.groupby("series")["previous"].shift(-1)
    df["revision"] = df["next_previous"] - df["actual"]
    return df.reset_index(drop=True)
