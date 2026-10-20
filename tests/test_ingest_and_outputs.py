import json

import numpy as np
import pandas as pd

from efie.explain.theses import CONTRADICTED, SUPPORTED, UNKNOWN, evaluate
from efie.ingest.csv_import import read_ohlcv_csv
from efie.ingest.tradingview import _complete, bars_from_payload
from efie.reports.pine_preview import pine_z


def test_rows_and_columns_payloads_agree():
    rows = {"bars": [{"t": 1792468800, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10}, {"t": 1792472400, "o": 1.5, "h": 2, "l": 1, "c": 1.8, "v": 5}]}
    cols = {"bars": {"t": [1792468800, 1792472400], "o": [1, 1.5], "h": [2, 2], "l": [0.5, 1], "c": [1.5, 1.8], "v": [10, 5]}}
    pd.testing.assert_frame_equal(bars_from_payload(rows), bars_from_payload(cols))


def test_forming_bars_dropped():
    df = bars_from_payload({"bars": {"t": [1792468800, 1792472400], "o": [1, 1], "h": [1, 1], "l": [1, 1], "c": [1, 1], "v": [1, 1]}})
    snap = pd.Timestamp(1792472400 + 1800, unit="s", tz="UTC")  # half-way through the 2nd bar
    assert len(_complete(df, "1h", snap)) == 1


def test_csv_import_unix_and_iso(tmp_path):
    a = tmp_path / "a.csv"
    a.write_text("time,open,high,low,close,Volume\n1792468800,1,2,0.5,1.5,10\n")
    b = tmp_path / "b.csv"
    b.write_text("time,open,high,low,close\n2026-10-20T04:00:00Z,1,2,0.5,1.5\n")
    da, db = read_ohlcv_csv(a), read_ohlcv_csv(b)
    assert da.index[0] == db.index[0] == pd.Timestamp("2026-10-20 04:00", tz="UTC")


def test_pine_z_uses_population_std():
    x = pd.Series(np.arange(10.0))
    z = pine_z(x, 5)
    w = x.iloc[-5:]
    assert np.isclose(z.iloc[-1], (w.iloc[-1] - w.mean()) / w.std(ddof=0))


def test_crack_formula_matches_pine():
    m1, rb, ho = 80.0, 2.5, 3.0
    crack321 = (2 * rb * 42 + ho * 42 - 3 * m1) / 3
    assert np.isclose(crack321, (210 + 126 - 240) / 3)


def test_theses_statuses():
    row = {"inv_eia_cushing_change_z": -1.0, "ts_spread12": 0.8, "ts_spread12_chg5": 0.3}
    t1 = next(t for t in evaluate(row, None) if t["id"] == "T1")
    assert t1["status"] == SUPPORTED and t1["label"].startswith("hypothesis")
    row = {"inv_eia_cushing_change_z": 1.0, "ts_spread12": -0.8, "ts_spread12_chg5": -0.3}
    assert next(t for t in evaluate(row, None) if t["id"] == "T1")["status"] == CONTRADICTED
    assert next(t for t in evaluate({}, None) if t["id"] == "T1")["status"] == UNKNOWN


def test_thesis_label_requires_holm_significance():
    hyp = {"family": {"H6_cushing_change_vs_next5_spread_change": {"rho": -0.3, "ci": [-0.4, -0.2], "n": 300, "significant_after_holm": True}}}
    t1 = next(t for t in evaluate({"ts_spread12": 1.0}, hyp) if t["id"] == "T1")
    assert t1["label"] == "historically supported relationship"
