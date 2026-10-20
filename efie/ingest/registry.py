"""What each series is, where it comes from, and how it may be used."""

from __future__ import annotations

# Market series. ``symbol`` is the TradingView routing symbol; ``close_known`` says when a
# bar's close is known relative to the CME 17:00 ET session close (used for daily PIT rules).
MARKET_SERIES: dict[str, dict] = {
    "CL1": {"symbol": "NYMEX:CL1!", "unit": "USD/bbl", "desc": "WTI crude, front month (continuous, unadjusted)"},
    "CL2": {"symbol": "NYMEX:CL2!", "unit": "USD/bbl", "desc": "WTI crude, second month (continuous, unadjusted)"},
    "MCL1": {"symbol": "NYMEX:MCL1!", "unit": "USD/bbl", "desc": "Micro WTI, front month"},
    "RB1": {"symbol": "NYMEX:RB1!", "unit": "USD/gal", "desc": "RBOB gasoline, front month"},
    "HO1": {"symbol": "NYMEX:HO1!", "unit": "USD/gal", "desc": "NY Harbor ULSD (heating oil), front month"},
    "BRN1": {"symbol": "ICEEUR:BRN1!", "unit": "USD/bbl", "desc": "ICE Brent, front month"},
    "TL1": {
        "symbol": "NYMEX:TL1!",
        "unit": "USD/mt",
        "desc": "Freight futures, TD3C Middle East→China VLCC (Baltic), front month settlement",
    },
    "BWET": {"symbol": "AMEX:BWET", "unit": "USD/share", "desc": "Breakwave Tanker Shipping ETF (holds TD3C/TD20 freight futures)"},
}

SYMBOL_TO_SERIES = {v["symbol"]: k for k, v in MARKET_SERIES.items()}

# Scheduled releases taken from the TradingView economic calendar (US). The calendar
# gives, per release: the UTC timestamp, the first-print actual, the consensus forecast
# (when one was polled) and the prior value as shown at release time.
CALENDAR_SERIES: dict[str, dict] = {
    "ECONOMICS:USCOSC": {"name": "eia_crude", "desc": "EIA crude oil stocks change", "unit": "bbl", "sign": -1},
    "ECONOMICS:USGSCH": {"name": "eia_gasoline", "desc": "EIA gasoline stocks change", "unit": "bbl", "sign": -1},
    "ECONOMICS:USDFS": {"name": "eia_distillate", "desc": "EIA distillate stocks change", "unit": "bbl", "sign": -1},
    "ECONOMICS:USCCOS": {"name": "eia_cushing", "desc": "EIA Cushing crude stocks change", "unit": "bbl", "sign": -1},
    "ECONOMICS:USRCR": {"name": "eia_runs", "desc": "EIA refinery crude runs change", "unit": "bbl/d", "sign": +1},
    "ECONOMICS:USCOI": {"name": "eia_imports", "desc": "EIA crude oil imports change", "unit": "bbl/d", "sign": -1},
    "ECONOMICS:USGPRO": {"name": "eia_gasoline_prod", "desc": "EIA gasoline production change", "unit": "bbl/d", "sign": 0},
    "ECONOMICS:USDFP": {"name": "eia_distillate_prod", "desc": "EIA distillate production change", "unit": "bbl/d", "sign": 0},
    "ECONOMICS:USHOS": {"name": "eia_heating_oil", "desc": "EIA heating oil stocks change", "unit": "bbl", "sign": -1},
    "ECONOMICS:USCSC": {"name": "api_crude", "desc": "API crude oil stock change", "unit": "bbl", "sign": -1},
    "ECONOMICS:USCOR": {"name": "bh_oil_rigs", "desc": "Baker Hughes oil rig count", "unit": "rigs", "sign": 0},
    "ECONOMICS:USTRG": {"name": "bh_total_rigs", "desc": "Baker Hughes total rig count", "unit": "rigs", "sign": 0},
}

# The brief's data domains, and what milestone 1 can genuinely cover.
DOMAINS = {
    "freight": "TD3C VLCC freight futures (TL1, ends 2026-06-08 in this feed) and BWET tanker-freight ETF. "
    "No Baltic Exchange index licence, no TD25/TD22 history worth using (sparse, zero volume).",
    "physical_deliveries": "Proxy only: EIA Cushing stock changes and front-spread behaviour near expiry. "
    "No CME delivery notices, no pipeline-flow or vessel-tracking data.",
    "refinery_activity": "EIA refinery crude runs and gasoline/distillate production changes. No utilisation %.",
    "cracks": "Front-month RBOB and ULSD vs WTI (3-2-1, gasoline and diesel cracks).",
    "term_structure": "CL1–CL2 only; TradingView offers no deeper continuous contracts (CL3! etc. invalid).",
    "inventories": "EIA weekly (crude, gasoline, distillate, Cushing) and API crude, first-print with consensus.",
    "geopolitical": "No historical point-in-time event feed. A PIT-safe manual catalyst log is provided "
    "(empty: nothing is back-filled or invented).",
}
