"""Release schedule for the Pine indicator's "Release schedule" input.

Pine cannot read the economic calendar, and a fixed Wed 10:30 / Tue 16:30 ET rule is
wrong in holiday weeks. EFIE knows the published schedule (past releases and the
calendar's forward window), so it writes it as a compact string to paste into the
indicator: ``E<unix ms>`` for EIA crude, ``A<unix ms>`` for API crude, comma-separated,
no spaces. The same parsing and marking rules are mirrored in ``pine_preview`` and tested.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from efie.features.build import MarketData
from efie.market.sessions import ET
from efie.paths import DASHBOARD_DIR

KINDS = {"eia_crude": "E", "api_crude": "A"}


def schedule_string(md: MarketData, weeks_back: int = 10) -> str:
    ev = md.events
    start = md.snapshot - pd.Timedelta(weeks=weeks_back)
    rows = ev[ev["series"].isin(list(KINDS)) & (ev["release_ts"] >= start)].sort_values("release_ts")
    rows = rows.drop_duplicates(subset=["series", "release_ts"])
    ms = pd.DatetimeIndex(rows["release_ts"]).as_unit("ms").asi8
    return ",".join(f"{KINDS[s]}{int(t)}" for s, t in zip(rows["series"], ms))


def parse(sched: str) -> dict[str, list[int]]:
    """Mirror of the Pine parser: tokens shorter than two characters or unparseable are ignored."""
    out = {"E": [], "A": []}
    for tok in sched.split(","):
        if len(tok) > 1 and tok[0] in out:
            try:
                out[tok[0]].append(int(float(tok[1:])))
            except ValueError:
                continue
    return out


def mark(index: pd.DatetimeIndex, sched: str, bar: pd.Timedelta = pd.Timedelta(hours=1)) -> pd.DataFrame:
    """Mirror of the Pine marking: listed times from the first listed one on, the weekly rule before."""
    p = parse(sched)
    every = p["E"] + p["A"]
    start = min(every) if every else None
    # Explicit unit: pandas indexes are not always nanosecond-based.
    open_ms = pd.DatetimeIndex(index).as_unit("ms").asi8.astype(np.int64)
    close_ms = open_ms + int(bar.total_seconds() * 1000)

    def listed(times):
        hit = np.zeros(len(index), dtype=bool)
        for t0 in times:
            hit |= (t0 >= open_ms) & (t0 < close_ms)
        return hit

    et = index.tz_convert(ET)
    rule_eia = (et.dayofweek == 2) & (et.hour == 10)
    rule_api = (et.dayofweek == 1) & (et.hour == 16)
    use_list = np.zeros(len(index), dtype=bool) if start is None else close_ms > start
    return pd.DataFrame(
        {
            "eia_window": np.where(use_list, listed(p["E"]), rule_eia),
            "api_window": np.where(use_list, listed(p["A"]), rule_api),
        },
        index=index,
    )


def write_schedule(md: MarketData) -> str:
    s = schedule_string(md)
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    out = DASHBOARD_DIR / "pine_schedule.txt"
    out.write_text(s + "\n")
    return str(out)


# Usual weekday and ET clock time; holiday weeks move to another weekday (e.g. Thursday).
USUAL = {"E": (2, "10:30"), "A": (1, "16:30")}


def describe(sched: str, after: pd.Timestamp) -> list[str]:
    """Upcoming releases in ET. An entry on the usual weekday but at an unusual clock time is
    flagged rather than corrected: it is usually a forward entry the calendar has not yet
    adjusted for a daylight-saving change, and it gets fixed before the release."""
    p = parse(sched)
    rows = []
    for k, label in (("E", "EIA"), ("A", "API")):
        for t in sorted(p[k]):
            ts = pd.Timestamp(t, unit="ms", tz="UTC").tz_convert(ET)
            if ts <= after:
                continue
            note = ""
            dow, hhmm = USUAL[k]
            if ts.dayofweek == dow and f"{ts:%H:%M}" != hhmm:
                note = f" (unusual time; usually {hhmm} ET — regenerate the schedule nearer the date)"
            rows.append(f"{label} {ts:%a %d %b %H:%M} ET{note}")
    return rows
