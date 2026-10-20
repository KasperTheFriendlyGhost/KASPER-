"""Thesis board: how the fundamental observations fit together right now.

A thesis is a named, falsifiable story about the crude market with explicit conditions
that would *strengthen* or *invalidate* it. Each condition is checked against the current
point-in-time values. Every thesis also carries its historical test result (from the
pre-registered hypotheses); unless that test survived the Holm correction the thesis is
labelled a hypothesis, not a signal — institutional commentary that tells the same story
does not change that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

SUPPORTED, MIXED, CONTRADICTED, UNKNOWN = "supported", "mixed", "contradicted", "cannot evaluate"


@dataclass
class Observation:
    label: str
    key: str
    strengthens: Callable[[float], bool]
    invalidates: Callable[[float], bool]
    fmt: str = "{:+.2f}"


@dataclass
class Thesis:
    id: str
    title: str
    claim: str
    lean: str  # what the thesis implies for WTI if it holds
    observations: list[Observation]
    evidence: list[str] = field(default_factory=list)  # hypothesis ids


def _num(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return v


THESES: list[Thesis] = [
    Thesis(
        "T1",
        "Hub tightness",
        "Cushing is drawing and the prompt spread is firming: barrels are scarce at the delivery point.",
        "bullish front month / M1–M2 spread",
        [
            Observation("Cushing change (z, latest EIA)", "inv_eia_cushing_change_z", lambda v: v < -0.5, lambda v: v > 0.5),
            Observation("M1–M2 spread (USD/bbl)", "ts_spread12", lambda v: v > 0, lambda v: v < 0),
            Observation("M1–M2 spread, 5-session change", "ts_spread12_chg5", lambda v: v > 0.1, lambda v: v < -0.1),
        ],
        ["H6_cushing_change_vs_next5_spread_change", "H8_spread12_pct_vs_next_session"],
    ),
    Thesis(
        "T2",
        "Refinery pull",
        "Refiners are running harder on healthy margins, so crude draws are demand-driven.",
        "bullish crude",
        [
            Observation("Refinery crude runs change (z)", "inv_eia_runs_change_z", lambda v: v > 0.5, lambda v: v < -0.5),
            Observation("3-2-1 crack (z, 250 sessions)", "crk_321_z", lambda v: v > 0.5, lambda v: v < -0.5),
            Observation("3-2-1 crack, 5-session change (USD/bbl)", "crk_321_chg5", lambda v: v > 0, lambda v: v < -1.0),
            Observation("Crude surprise vs consensus (z)", "inv_eia_crude_surprise_z", lambda v: v < -0.5, lambda v: v > 0.5),
        ],
        ["H7_crack321_chg5_vs_next_session"],
    ),
    Thesis(
        "T3",
        "Product overhang",
        "Gasoline and distillate are building faster than expected while margins fade.",
        "bearish crude (via refinery margins)",
        [
            Observation("Gasoline surprise (z)", "inv_eia_gasoline_surprise_z", lambda v: v > 0.5, lambda v: v < -0.5),
            Observation("Distillate surprise (z)", "inv_eia_distillate_surprise_z", lambda v: v > 0.5, lambda v: v < -0.5),
            Observation("Diesel crack, 5-session change (USD/bbl)", "crk_diesel_chg5", lambda v: v < -1.0, lambda v: v > 1.0),
        ],
        ["H7_crack321_chg5_vs_next_session"],
    ),
    Thesis(
        "T4",
        "Export arbitrage",
        "A wide Brent–WTI spread with easing VLCC freight pulls US barrels to export.",
        "supportive for WTI relative to Brent",
        [
            Observation("Brent–WTI spread (z, 250 sessions)", "arb_brent_wti_z250", lambda v: v > 0.5, lambda v: v < -0.5),
            Observation("TD3C freight, 5-day log change", "frt_td3c_chg5", lambda v: v < -0.05, lambda v: v > 0.10, "{:+.1%}"),
            Observation("BWET (tanker freight ETF), 5-day log change", "frt_bwet_chg5", lambda v: v < -0.05, lambda v: v > 0.10, "{:+.1%}"),
        ],
        ["H9_td3c_chg5_vs_next5_brent_wti_change", "H10_td3c_chg5_vs_next_session"],
    ),
    Thesis(
        "T5",
        "Inventory news already priced",
        "The API report the evening before already told the market most of what EIA said.",
        "no post-release drift expected",
        [
            Observation("API crude surprise (z)", "inv_api_crude_surprise_z", lambda v: abs(v) > 0.5, lambda v: False),
            Observation("EIA crude vs API figure (z)", "inv_eia_minus_api_z", lambda v: abs(v) < 0.5, lambda v: abs(v) > 1.5),
        ],
        ["H4_api_surprise_predicts_eia_surprise", "H5_api_change_drift_until_eia", "H3_eia_surprise_next_session"],
    ),
]


def evaluate(row: dict, hypotheses: dict | None) -> list[dict]:
    fam = (hypotheses or {}).get("family", {})
    out = []
    for t in THESES:
        obs, n_s, n_i, n_known = [], 0, 0, 0
        for o in t.observations:
            v = _num(row.get(o.key))
            if not np.isfinite(v):
                rolled = o.key.startswith(("ts_", "crk_")) and o.key.endswith(("_chg5", "_chg24"))
                why = "n/a — contract roll inside the window" if rolled else "n/a — stale or no current data"
                obs.append({"label": o.label, "value": None, "display": why, "state": "missing"})
                continue
            n_known += 1
            s, i = bool(o.strengthens(v)), bool(o.invalidates(v))
            n_s += s
            n_i += i
            obs.append({"label": o.label, "value": v, "display": o.fmt.format(v), "state": "strengthens" if s else "invalidates" if i else "neutral"})
        if n_known < max(1, len(t.observations) // 2 + (len(t.observations) % 2)):
            status = UNKNOWN
        elif n_s and not n_i:
            status = SUPPORTED
        elif n_i and not n_s:
            status = CONTRADICTED
        else:
            status = MIXED
        ev = []
        for h in t.evidence:
            r = fam.get(h)
            if r:
                ev.append(
                    {
                        "id": h,
                        "rho": r.get("rho"),
                        "ci": r.get("ci"),
                        "n": r.get("n"),
                        "significant_after_holm": bool(r.get("significant_after_holm")),
                    }
                )
        validated = any(e["significant_after_holm"] for e in ev)
        out.append(
            {
                "id": t.id,
                "title": t.title,
                "claim": t.claim,
                "lean": t.lean,
                "status": status,
                "observations": obs,
                "evidence": ev,
                "label": "historically supported relationship" if validated else "hypothesis — not a validated signal",
            }
        )
    return out


def interpretations(row: dict) -> list[str]:
    """Plain-language readings of how the latest observations interact."""
    g = lambda k: _num(row.get(k))  # noqa: E731
    lines = []
    crude, runs, imp = g("inv_eia_crude_change_z"), g("inv_eia_runs_change_z"), g("inv_eia_imports_change_z")
    if np.isfinite(crude) and crude < -0.5:
        if np.isfinite(runs) and runs > 0.5:
            lines.append("Crude drew while refinery runs rose: the draw looks demand-led (refiners pulling barrels).")
        elif np.isfinite(imp) and imp < -0.5:
            lines.append("Crude drew while imports fell: the draw looks supply/logistics-led rather than demand-led.")
        else:
            lines.append("Crude drew without a matching rise in runs or fall in imports: check exports and the adjustment line in the EIA report.")
    elif np.isfinite(crude) and crude > 0.5:
        if np.isfinite(runs) and runs < -0.5:
            lines.append("Crude built while runs fell: refinery outages or maintenance are a likely cause.")
        else:
            lines.append("Crude built without a fall in runs: weaker exports or higher imports/production are likely.")
    gas, dist, crk = g("inv_eia_gasoline_surprise_z"), g("inv_eia_distillate_surprise_z"), g("crk_321_chg5")
    if np.isfinite(gas) and np.isfinite(dist) and np.isfinite(crk):
        if gas > 0.5 and dist > 0.5 and crk < 0:
            lines.append("Both products built more than expected and the 3-2-1 crack weakened: margin pressure can feed back into lower crude demand.")
        elif gas < -0.5 and dist < -0.5 and crk > 0:
            lines.append("Both products drew more than expected and the crack firmed: refining margins support crude demand.")
    cush, spr = g("inv_eia_cushing_change_z"), g("ts_spread12_chg5")
    if np.isfinite(cush) and np.isfinite(spr):
        if cush < -0.5 and spr > 0:
            lines.append("Cushing drew and the prompt spread firmed: consistent with tightness at the delivery hub.")
        elif cush < -0.5 and spr < 0:
            lines.append("Cushing drew but the prompt spread weakened: the hub draw is not (yet) showing in the curve.")
        elif cush > 0.5 and spr > 0:
            lines.append("Cushing built yet the prompt spread firmed: the curve is being driven by something other than the hub.")
    api, ema = g("inv_api_crude_surprise_z"), g("inv_eia_minus_api_z")
    if np.isfinite(api) and np.isfinite(ema):
        if abs(ema) < 0.5:
            lines.append("EIA landed close to the API figure: most of the inventory news was available the evening before.")
        elif abs(ema) > 1.5:
            lines.append("EIA differed sharply from the API figure: this week's EIA print carried genuinely new information.")
    td3c, bwet = g("frt_td3c_chg5"), g("frt_bwet_chg5")
    if not np.isfinite(td3c) and np.isfinite(bwet):
        lines.append("TD3C freight futures are stale in this feed; BWET (an ETF of freight futures) is the only live freight read.")
    return lines
