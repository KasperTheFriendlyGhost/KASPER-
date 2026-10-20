"""Geopolitical and supply catalysts — a point-in-time log you maintain.

No historical event feed is available in this environment, and nothing here is
back-filled from memory: an event enters the log when you (or a later data feed) record
it, and ``logged_at_utc`` is when that happened. A catalyst counts as known at time ``t``
only if ``logged_at_utc <= t``; that keeps the log usable in back-tests later without
hindsight. Until the log has history, catalysts are shown in reports for context only and
are not model inputs.

File: ``config/catalysts.csv`` with columns
``event_id, logged_at_utc, starts_utc, ends_utc, category, region, description, source_url``.
Categories in use: ``supply_outage``, ``sanctions``, ``opec_policy``, ``shipping_disruption``,
``conflict``, ``weather``, ``policy_other``.
"""

from __future__ import annotations

import pandas as pd

from efie.paths import ROOT

LOG = ROOT / "config" / "catalysts.csv"
COLUMNS = ["event_id", "logged_at_utc", "starts_utc", "ends_utc", "category", "region", "description", "source_url"]


def load_log() -> pd.DataFrame:
    if not LOG.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(LOG, dtype=str).fillna("")
    for c in ("logged_at_utc", "starts_utc", "ends_utc"):
        df[c] = pd.to_datetime(df[c].replace("", None), utc=True, errors="coerce")
    return df


def known_at(asof: pd.Timestamp) -> pd.DataFrame:
    """Catalysts that had been logged by ``asof`` and are active at it."""
    df = load_log()
    if df.empty:
        return df
    asof = pd.Timestamp(asof)
    known = df[df["logged_at_utc"] <= asof]
    active = known[(known["starts_utc"] <= asof) & (known["ends_utc"].isna() | (known["ends_utc"] >= asof))]
    return active.reset_index(drop=True)
