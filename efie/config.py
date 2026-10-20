"""Configuration loading (``config/efie.toml``)."""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from efie.paths import CONFIG_FILE


@lru_cache(maxsize=4)
def load_config(path: str | None = None) -> dict[str, Any]:
    with open(Path(path) if path else CONFIG_FILE, "rb") as f:
        return tomllib.load(f)


def round_trip_cost_usd(cfg: dict[str, Any], multiplier: float = 1.0) -> float:
    """Cost of opening and closing one contract, in USD."""
    c = cfg["costs"]
    i = cfg["instrument"]
    per_side = c["commission_per_side_usd"] + c["slippage_ticks_per_side"] * i["tick_value_usd"]
    return 2.0 * per_side * multiplier


def cost_per_side_usd(cfg: dict[str, Any], multiplier: float = 1.0) -> float:
    return round_trip_cost_usd(cfg, multiplier) / 2.0
