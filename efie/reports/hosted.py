"""Store documents for the hosted EFIE dashboard (a claude.ai Dashboard artifact).

The hosted page (``hosted/index.html``) reads prices live from each reader's own
TradingView connection and the engine's row files (``dashboard/data/*.json``, written by
``dashboard_data``) as attached files. This module writes the documents that describe
those sources, so the first write and every refresh use the same titles and
descriptions::

    python -m efie hosted-docs urls.json

``urls.json`` maps each row file's name (``efie_forecasts``…) to the ``/_blob/<id>`` url
its upload returned. One JSON document per store entry goes to ``dashboard/store/``, plus
``batch.json`` listing them in the order the store expects (meta, datasets, page).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from efie.paths import DASHBOARD_DIR, ROOT
from efie.reports.dashboard_data import OUT as DATA_DIR

STORE_DIR = DASHBOARD_DIR / "store"
PAGE = ROOT / "hosted" / "index.html"
TITLE = "KASPER EFIE Desk"
BY = "EFIE engine, run by Claude"
SCHEDULE = "Rebuilt by the EFIE engine at 7 minutes past each hour, 07:07–17:07 ET on weekdays (a Claude scheduled task)."
STALE_AFTER_HOURS = 20

# Live daily bars, one TradingView call each: id → (symbol, title, what it is).
LIVE = {
    "cl1_d": ("NYMEX:CL1!", "WTI front month, daily", "NYMEX WTI crude front month (CL1!), unadjusted continuous, last 130 daily bars; the last bar is the session in progress."),
    "cl2_d": ("NYMEX:CL2!", "WTI second month, daily", "NYMEX WTI crude second month (CL2!), unadjusted continuous, last 130 daily bars."),
    "rb1_d": ("NYMEX:RB1!", "RBOB gasoline, daily", "NYMEX RBOB gasoline front month (RB1!), USD/gal, last 130 daily bars."),
    "ho1_d": ("NYMEX:HO1!", "ULSD diesel, daily", "NYMEX ULSD (heating oil) front month (HO1!), USD/gal, last 130 daily bars."),
    "brn1_d": ("ICEEUR:BRN1!", "Brent front month, daily", "ICE Brent crude front month (BRN1!), last 130 daily bars; needs ICE data on the reader's TradingView plan."),
    "bwet_d": ("AMEX:BWET", "Tanker freight ETF, daily", "BWET, an ETF of crude-tanker freight futures, last 130 daily bars."),
    "tl1_d": ("NYMEX:TL1!", "TD3C freight futures, daily", "NYMEX TD3C freight futures (TL1!, Middle East Gulf to China), last 130 daily bars; the feed has gaps and stopped updating in June 2026."),
}

ENGINE = "Written by the EFIE engine (Python walk-forward models over TradingView data) in Claude's session, which a dashboard cannot call, so it is a file rather than a live query."
FILES = {
    "efie_status": ("EFIE engine status", "The engine's latest run: curve regime, M1–M2 spread z over 240 hourly bars, 3-2-1 crack z over 250 sessions, and how many forecast horizons pass validation."),
    "efie_forecasts": ("Forecasts behind the gate", "1-hour, 4-hour and next-session WTI forecasts with each validation-gate verdict; a horizon that fails shows the climatology baseline instead of the model."),
    "efie_releases": ("Latest weekly releases", "Latest EIA, API and Baker Hughes releases from the TradingView economic calendar: first print, consensus, surprise, surprise z against the prior 52 releases and deviation from the same week of the prior five years."),
    "efie_surprises": ("EIA crude surprises, 26 weeks", "EIA weekly crude stock change minus consensus for the last 26 reports, million barrels, from the TradingView economic calendar."),
    "efie_schedule": ("Upcoming EIA and API releases", "Scheduled EIA and API weekly releases from the TradingView economic calendar, with holiday shifts and unusual times flagged."),
    "efie_pine_schedule": ("Pine release schedule", "EIA and API release times as the string the KASPER EFIE Research Pine indicator reads (E/A plus Unix milliseconds)."),
    "efie_notes": ("What changed and how it fits", "What changed since the previous hourly report, and how the inventory, refinery, freight and curve readings fit together."),
    "efie_theses": ("Thesis board", "Each fundamental thesis with today's readings for and against it and its pre-registered historical test; hypotheses, not validated signals."),
    "efie_validation": ("Walk-forward validation", "Out-of-sample Brier skill (with 95% block-bootstrap interval) and 80% range coverage for the technical-only and EFIE models at each horizon."),
    "efie_overlays": ("Overlay backtests after costs", "Change in USD per session per MCL contract from each EFIE overlay on three reference strategies, after commission, slippage and rolls, with Holm-corrected p-values."),
    "efie_freshness": ("Engine data freshness", "The newest bar or release each engine input had at the latest run."),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_hashes() -> dict[str, str]:
    return {name: sha256(DATA_DIR / f"{name}.json") for name in FILES if (DATA_DIR / f"{name}.json").exists()}


def live_doc(ds_id: str) -> dict:
    symbol, title, what = LIVE[ds_id]
    return {
        "title": title,
        "description": f"{what} Reads TradingView get_ohlcv {symbol}, 1D.",
        "source": {"kind": "query", "connector": "TradingView", "tool": "mcp-tv-get-ohlcv", "args": {"symbol": symbol, "interval": "1D", "count": 130, "format": "columns"}},
    }


def file_doc(name: str, url: str, at: str) -> dict:
    title, what = FILES[name]
    return {
        "title": title,
        "description": f"{what} {ENGINE}",
        "source": {"kind": "file", "url": url, "name": f"{name}.json"},
        "updated": {"at": at, "by": BY},
        "schedule": SCHEDULE,
        "staleAfterHours": STALE_AFTER_HOURS,
        "sha256": sha256(DATA_DIR / f"{name}.json"),
    }


def write_docs(urls: dict[str, str], at: str | None = None) -> Path:
    at = at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    missing = sorted(set(FILES) - set(urls))
    if missing:
        raise ValueError(f"no uploaded url for: {', '.join(missing)}")
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    plan = []

    def put(collection: str, doc_id: str, doc: dict):
        p = STORE_DIR / f"{collection}__{doc_id}.json"
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
        plan.append({"op": "set", "collection": collection, "doc_id": doc_id, "file_path": str(p)})

    put("dash", "meta", {"title": TITLE})
    for ds_id in LIVE:
        put("datasets", ds_id, live_doc(ds_id))
    for name in FILES:
        put("datasets", name, file_doc(name, urls[name], at))
    put("files", "index.html", {"text": PAGE.read_text()})
    out = STORE_DIR / "batch.json"
    out.write_text(json.dumps(plan, indent=1))
    return out
