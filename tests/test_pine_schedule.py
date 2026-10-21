import pandas as pd

from efie.reports.pine_schedule import describe, mark, parse, schedule_string


def _ms(s: str) -> int:
    return int(pd.Timestamp(s, tz="America/New_York").tz_convert("UTC").value // 1_000_000)


def test_parse_ignores_bad_tokens():
    p = parse(f"E{_ms('2026-11-12 12:00')},A{_ms('2026-11-10 16:30')},X1,E,Eabc,")
    assert p["E"] == [_ms("2026-11-12 12:00")] and p["A"] == [_ms("2026-11-10 16:30")]


def test_listed_times_override_rule_and_rule_applies_before():
    idx = pd.date_range("2026-11-02 00:00", "2026-11-14 00:00", freq="1h", tz="America/New_York").tz_convert("UTC")
    # Veterans Day week: EIA on Thursday 12:00 ET instead of Wednesday 10:30.
    sched = f"A{_ms('2026-11-10 16:30')},E{_ms('2026-11-12 12:00')}"
    m = mark(idx, sched)
    et = m.index.tz_convert("America/New_York")
    eia_bars = list(et[m["eia_window"]].strftime("%a %d %H:%M"))
    api_bars = list(et[m["api_window"]].strftime("%a %d %H:%M"))
    # Before the first listed time (Tue 10 Nov 16:30) the weekly rule marks Wed 4 Nov 10:00.
    assert "Wed 04 10:00" in eia_bars
    # From then on only listed times count: no mark on Wed 11 Nov, a mark on Thu 12 Nov 12:00.
    assert "Wed 11 10:00" not in eia_bars and "Thu 12 12:00" in eia_bars
    assert api_bars[-1] == "Tue 10 16:00"


def test_empty_schedule_falls_back_to_rule():
    idx = pd.date_range("2026-10-19", "2026-10-23", freq="1h", tz="America/New_York").tz_convert("UTC")
    m = mark(idx, "")
    et = m.index.tz_convert("America/New_York")
    assert list(et[m["eia_window"]].strftime("%a %H:%M")) == ["Wed 10:00"]
    assert list(et[m["api_window"]].strftime("%a %H:%M")) == ["Tue 16:00"]


def test_describe_flags_unusual_time():
    sched = f"E{_ms('2026-11-04 09:30')},E{_ms('2026-11-12 12:00')}"
    rows = describe(sched, pd.Timestamp("2026-10-21", tz="UTC"))
    assert "unusual time" in rows[0] and "unusual time" not in rows[1]


def test_schedule_string_from_synthetic(synthetic_md):
    s = schedule_string(synthetic_md, weeks_back=52)
    p = parse(s)
    assert p["E"] and p["A"] and all(t > 0 for t in p["E"])
