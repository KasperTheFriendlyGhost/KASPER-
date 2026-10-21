"""The hosted dashboard's store documents and the data pull plan."""

import json
import re
from datetime import date

from efie.ingest.plan import CHAIN, full_calls, refresh_calls
from efie.paths import ROOT
from efie.reports import hosted


def test_refresh_plan_windows():
    calls = refresh_calls(date(2026, 10, 21))
    assert len(calls) == 13
    cal = calls[-1]
    assert cal["tool"] == "mcp-tv-get-economic-calendar"
    assert cal["args"]["date_from"] == "2026-10-14" and cal["args"]["date_to"] == "2026-11-21T23:59:59Z"
    intraday = refresh_calls(date(2026, 10, 21), intraday=True)
    assert all(c["args"].get("interval") != "1D" for c in intraday) and len(intraday) == 7


def test_full_plan_chains_second_hourly_page():
    calls = full_calls(date(2026, 10, 21))
    p2 = [c for c in calls if c.get("dataset", "").endswith("_p2")]
    assert p2 and all(c["args"]["date_to"] == CHAIN for c in p2)
    # Each second page directly follows its first page.
    names = [c.get("dataset") for c in calls]
    for c in p2:
        i = names.index(c["dataset"])
        assert names[i - 1] == c["dataset"].replace("_p2", "_p1")
    assert not any("_r2" in (n or "") for n in names)


def test_live_docs_match_page():
    page = (ROOT / "hosted" / "index.html").read_text()
    used = set(re.findall(r'data-source="([a-z0-9_]+)"', page)) | set(re.findall(r"dash\.data\('([a-z0-9_]+)'\)", page))
    calcs = set(re.findall(r"dash\.calc\('([a-z0-9_]+)'", page))
    loaders = set(re.findall(r"dash\.loader\('([a-z0-9_]+)'", page))
    datasets = set(hosted.LIVE) | set(hosted.FILES)
    assert used - calcs <= datasets, used - calcs - datasets
    assert loaders == set(hosted.LIVE)
    for ds_id in hosted.LIVE:
        doc = hosted.live_doc(ds_id)
        assert doc["source"]["args"]["symbol"] in doc["description"]
        assert len(doc["title"]) <= 34


def test_file_docs_need_every_url(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(hosted, "STORE_DIR", tmp_path)
    with pytest.raises(ValueError):
        hosted.write_docs({"efie_status": "/_blob/x"})
