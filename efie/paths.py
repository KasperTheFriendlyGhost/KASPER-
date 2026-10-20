"""Filesystem layout. Everything lives under ``kasper/``; nothing outside it is touched."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("EFIE_ROOT", Path(__file__).resolve().parents[1]))
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"  # gitignored: licensed market data never enters git
PROCESSED_DIR = DATA_DIR / "processed"  # gitignored
REPORTS_DIR = ROOT / "reports"  # gitignored: generated hourly/daily reports
DASHBOARD_DIR = ROOT / "dashboard"  # generated dashboard (gitignored except README)
EVIDENCE_DIR = ROOT / "docs" / "evidence"  # committed: aggregate statistics only
CONFIG_FILE = ROOT / "config" / "efie.toml"
