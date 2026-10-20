"""Stage raw connector results into the local data store with provenance.

Data in this project is never typed in by hand. A connector result (for example a
TradingView ``get_ohlcv`` or ``get_economic_calendar`` response) is saved to disk by
the tool host; this module copies that file, byte for byte, into
``data/raw/<source>/`` and appends a manifest line recording the request, the file's
SHA-256 and when it was staged. Every downstream table can be traced back to a
manifest entry.

Usage::

    python -m efie.ingest.stage <saved_result_file> <dataset_name> '<request json>'
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from efie.paths import RAW_DIR

MANIFEST = "manifest.jsonl"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stage(src: Path, name: str, request: dict, source: str = "tradingview") -> dict:
    """Copy ``src`` to ``RAW_DIR/source/name.json`` and record it in the manifest."""
    src = Path(src)
    payload = json.loads(src.read_text())
    if not payload.get("success", payload.get("status") == "ok"):
        raise ValueError(f"{src} is not a successful result: {str(payload)[:200]}")
    dest_dir = RAW_DIR / source
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{name}.json"
    shutil.copyfile(src, dest)
    entry = {
        "dataset": name,
        "source": source,
        "file": str(dest.relative_to(RAW_DIR)),
        "sha256": sha256(dest),
        "bytes": dest.stat().st_size,
        "request": request,
        "staged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "origin": src.name,
    }
    with open(dest_dir / MANIFEST, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def read_manifest(source: str = "tradingview") -> list[dict]:
    path = RAW_DIR / source / MANIFEST
    if not path.exists():
        return []
    entries = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    # The latest staging of a dataset name wins.
    latest: dict[str, dict] = {}
    for e in entries:
        latest[e["dataset"]] = e
    return list(latest.values())


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    print(json.dumps(stage(Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3]))))
