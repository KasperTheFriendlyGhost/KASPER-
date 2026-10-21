"""The connector calls that keep the local data store current.

``python -m efie pull-plan`` prints them as JSON lines, one TradingView call each (the
connector's tool name and its arguments). Run every call, then stage what the tool host
saved with ``python -m efie stage-auto <files>``; staging names each file from its own
content, so the calls can run in any order or in parallel.

- default (refresh): overlapping windows — the latest 5,000 hourly bars per contract, the
  daily series from 2010, and the economic calendar from a week back to 31 days ahead.
- ``--intraday``: only the hourly bars and the calendar, for runs between settlements (the
  daily series change once a session).
- ``--full`` (a machine or session with an empty ``data/raw``): the requests recorded in
  ``docs/evidence/data_manifest.jsonl`` — deep hourly history in two pages and the calendar
  in ≤ 6.5-week windows — followed by a refresh.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from efie.paths import EVIDENCE_DIR

OHLCV = "mcp-tv-get-ohlcv"
CALENDAR = "mcp-tv-get-economic-calendar"
HOURLY = ["NYMEX:CL1!", "NYMEX:CL2!", "NYMEX:MCL1!", "NYMEX:RB1!", "NYMEX:HO1!", "AMEX:BWET"]
DAILY = ["NYMEX:CL1!", "NYMEX:CL2!", "NYMEX:RB1!", "NYMEX:HO1!", "ICEEUR:BRN1!", "NYMEX:TL1!"]
# A second hourly page continues where the first one stopped: pass the first answer's
# `next_date_to` as its `date_to`.
CHAIN = "$next_date_to"


def refresh_calls(today: date, intraday: bool = False) -> list[dict]:
    calls = [
        {"tool": OHLCV, "args": {"symbol": s, "interval": "1h", "date_from": (today - timedelta(days=3 * 365)).isoformat(), "count": 5000, "format": "rows"}}
        for s in HOURLY
    ]
    if not intraday:
        calls += [{"tool": OHLCV, "args": {"symbol": s, "interval": "1D", "date_from": "2010-01-01", "count": 5000, "format": "rows"}} for s in DAILY]
    calls.append(
        {"tool": CALENDAR, "args": {"countries": "US", "date_from": (today - timedelta(days=7)).isoformat(), "date_to": f"{today + timedelta(days=31)}T23:59:59Z"}}
    )
    return calls


def full_calls(today: date) -> list[dict]:
    entries = [json.loads(line) for line in (EVIDENCE_DIR / "data_manifest.jsonl").read_text().splitlines() if line.strip()]
    first = [e for e in entries if "_r2" not in e["dataset"]]
    calls = []
    for e in sorted(first, key=lambda e: e["dataset"]):
        r = e["request"]
        if r["tool"] == "get_ohlcv":
            args = {k: v for k, v in r.items() if k != "tool"}
            if e["dataset"].endswith("_p2"):
                args["date_to"] = CHAIN
            calls.append({"tool": OHLCV, "args": args, "dataset": e["dataset"]})
        elif e["dataset"].startswith("cal_"):
            _, d0, d1 = e["dataset"].split("_")[:3]
            calls.append({"tool": CALENDAR, "args": {"countries": "US", "date_from": d0, "date_to": f"{d1}T23:59:59Z"}, "dataset": e["dataset"]})
    return calls + refresh_calls(today)
