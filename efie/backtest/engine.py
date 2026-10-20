"""P&L accounting for MCL positions, net of commissions, slippage and rolls.

Hourly: a position decided at the close of bar ``t`` is filled at that close and earns
bar ``t+1``'s contract-consistent price change. Changing position costs
``|Δposition| × cost per side``. A position carried into a roll bar is rolled at the
session open and pays a full round trip.

Daily: a position decided at the 17:00 ET close of session ``D`` is filled at the next
session's 18:00 ET open (the daily close is the 14:30 ET settlement, which is already
past). It earns that session's open→settle move; the settle→open gap before it is earned
by the position that was held until then.

Every result is reported at the configured costs and at ``stress_multiplier`` × costs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from efie.config import cost_per_side_usd


def hourly_pnl(frame: pd.DataFrame, pos: pd.Series, cfg: dict, cost_mult: float = 1.0) -> pd.DataFrame:
    mult = cfg["instrument"]["multiplier_bbl"]
    cps = cost_per_side_usd(cfg, cost_mult)
    pos = pos.reindex(frame.index).fillna(0.0)
    held = pos.shift(1).fillna(0.0)
    gross = held * frame["dP"].fillna(0.0) * mult
    traded = (pos - held).abs()
    roll = frame["roll"].fillna(False).astype(bool)
    costs = traded * cps + held.abs() * roll * 2 * cps
    out = pd.DataFrame({"gross": gross, "costs": costs, "net": gross - costs, "held": held, "traded": traded})
    out["trading_date"] = frame["trading_date"].to_numpy()
    return out


def daily_pnl(frame: pd.DataFrame, pos: pd.Series, cfg: dict, cost_mult: float = 1.0) -> pd.DataFrame:
    """P&L of each session, indexed by that session's trading date."""
    mult = cfg["instrument"]["multiplier_bbl"]
    cps = cost_per_side_usd(cfg, cost_mult)
    pos = pos.reindex(frame.index).fillna(0.0)
    prev = pos.shift(1).fillna(0.0)
    gross_next = (prev * frame["gap_next"].fillna(0.0) + pos * frame["intraday_next"].fillna(0.0)) * mult
    traded = (pos - prev).abs()
    roll_next = frame["roll"].shift(-1, fill_value=False).astype(bool)
    cost_next = traded * cps + prev.abs() * roll_next * 2 * cps
    out = pd.DataFrame(
        {
            "gross": gross_next.shift(1).fillna(0.0),
            "costs": cost_next.shift(1).fillna(0.0),
            "held": pos.shift(1).fillna(0.0),
            "traded": traded.shift(1).fillna(0.0),
        },
        index=frame.index,
    )
    out["net"] = out["gross"] - out["costs"]
    out["trading_date"] = frame.index
    return out


def session_series(pnl: pd.DataFrame) -> pd.Series:
    return pnl.groupby("trading_date")["net"].sum()


def summarize(pnl: pd.DataFrame) -> dict:
    daily = session_series(pnl)
    eq = daily.cumsum()
    dd = eq - eq.cummax()
    wins, losses = daily[daily > 0].sum(), -daily[daily < 0].sum()
    sd = daily.std()
    return {
        "sessions": int(len(daily)),
        "net_usd": float(daily.sum()),
        "gross_usd": float(pnl["gross"].sum()),
        "costs_usd": float(pnl["costs"].sum()),
        "sharpe_annual": float(daily.mean() / sd * np.sqrt(252)) if sd > 0 else float("nan"),
        "max_drawdown_usd": float(dd.min()),
        "profit_factor": float(wins / losses) if losses > 0 else float("nan"),
        "contracts_traded": float(pnl["traded"].sum()),
        "exposure": float((pnl["held"] != 0).mean()),
        "session_hit_rate": float((daily > 0).mean()),
    }
