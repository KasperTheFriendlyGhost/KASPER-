"""Import OHLCV exported from TradingView ("Export chart data…") or any broker CSV.

This is how the pipeline runs on your own machine without the connector. The file is
copied into ``data/raw/csv/`` and recorded in that folder's manifest; nothing is edited.

Accepted columns (case-insensitive): ``time`` (Unix seconds or ISO-8601; naive times are
read as UTC unless ``--tz`` is given), ``open``, ``high``, ``low``, ``close`` and optionally
``volume``. For TradingView exports, ``time`` is the bar's open time, which is what EFIE uses.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from efie.ingest.registry import MARKET_SERIES
from efie.ingest.stage import sha256
from efie.paths import RAW_DIR

CSV_DIR = RAW_DIR / "csv"


def read_ohlcv_csv(path: Path, tz: str = "UTC") -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}
    need = ["time", "open", "high", "low", "close"]
    missing = [c for c in need if c not in cols]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}; found {list(df.columns)}")
    t = df[cols["time"]]
    if pd.api.types.is_numeric_dtype(t):
        idx = pd.to_datetime(t.astype("int64"), unit="s", utc=True)
    else:
        idx = pd.to_datetime(t, utc=False)
        idx = idx.dt.tz_localize(tz) if idx.dt.tz is None else idx
        idx = idx.dt.tz_convert("UTC")
    out = pd.DataFrame(
        {
            "o": df[cols["open"]].astype(float).values,
            "h": df[cols["high"]].astype(float).values,
            "l": df[cols["low"]].astype(float).values,
            "c": df[cols["close"]].astype(float).values,
            "v": df[cols["volume"]].astype(float).values if "volume" in cols else 0.0,
        },
        index=pd.DatetimeIndex(idx, name="t"),
    )
    return out.sort_index()


def import_csv(path: Path, series: str, interval: str, tz: str = "UTC") -> dict:
    if series not in MARKET_SERIES:
        raise ValueError(f"unknown series {series}; expected one of {sorted(MARKET_SERIES)}")
    read_ohlcv_csv(path, tz)  # validate before copying
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc)
    dest = CSV_DIR / f"{series}_{interval}_{stamp:%Y%m%dT%H%M%S}.csv"
    shutil.copyfile(path, dest)
    entry = {
        "series": series,
        "interval": interval,
        "tz": tz,
        "file": dest.name,
        "sha256": sha256(dest),
        "origin": str(path),
        "staged_at": stamp.isoformat(timespec="seconds"),
    }
    with open(CSV_DIR / "manifest.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def load_csv_frames(series: str, interval: str) -> list[tuple[pd.Timestamp, pd.DataFrame]]:
    path = CSV_DIR / "manifest.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        e = json.loads(line)
        if e["series"] == series and e["interval"] == interval:
            snap = pd.Timestamp(e["staged_at"])
            df = read_ohlcv_csv(CSV_DIR / e["file"], e.get("tz", "UTC"))
            # Exported charts include the forming bar; drop anything not closed at export time.
            step = pd.Timedelta(hours=1) if interval == "1h" else pd.Timedelta(days=1)
            out.append((snap, df[df.index + step <= snap]))
    return out
