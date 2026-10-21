# Runbook — exact commands

All commands run from the repository root. Python 3.11+.

## One-time setup

```bash
cd KASPER-
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Getting data

Market data is licensed and is **not in git**. Each machine or session stages its own copy into `data/raw/`.

**A. In a Claude Code session with the TradingView connector** (how the milestone-1 evidence was produced):
ask Claude to "refresh the EFIE data". It repeats the requests listed in `docs/evidence/data_manifest.jsonl`
(OHLCV for `NYMEX:CL1!`, `CL2!`, `MCL1!`, `RB1!`, `HO1!` hourly; `CL1!`, `CL2!`, `RB1!`, `HO1!`, `ICEEUR:BRN1!`,
`NYMEX:TL1!` daily; `AMEX:BWET` hourly; the US economic calendar in ≤ 6.5-week windows) and stages each saved
result byte-for-byte:

```bash
python -m efie stage-auto <saved_result_file> [<more files> …]   # names each file from its own content
python -m efie stage <saved_result_file> <dataset_name> '{"tool":"get_ohlcv","symbol":"NYMEX:CL1!","interval":"1h","date_from":"2015-01-01","count":8000,"format":"columns"}'
```

A refresh only needs overlapping windows: the latest 5,000 hourly bars per contract (rows format), the
daily series from 2010, and the calendar from a week back to its forward limit (~31 days). Later snapshots
win where they overlap; forming bars are dropped automatically.

**B. On your own machine, prices from TradingView chart exports** (chart → ⋯ → *Export chart data…*, ISO time):

```bash
python -m efie import-csv CL1_60.csv  --series CL1  --interval 1h
python -m efie import-csv CL2_60.csv  --series CL2  --interval 1h
python -m efie import-csv RB1_60.csv  --series RB1  --interval 1h
python -m efie import-csv HO1_60.csv  --series HO1  --interval 1h
python -m efie import-csv CL1_1D.csv  --series CL1  --interval 1D
python -m efie import-csv CL2_1D.csv  --series CL2  --interval 1D
python -m efie import-csv RB1_1D.csv  --series RB1  --interval 1D
python -m efie import-csv HO1_1D.csv  --series HO1  --interval 1D
python -m efie import-csv BRN1_1D.csv --series BRN1 --interval 1D
python -m efie import-csv TL1_1D.csv  --series TL1  --interval 1D
python -m efie import-csv BWET_60.csv --series BWET --interval 1h
```

The EIA/API calendar with consensus has no CSV path yet; on your machine copy `data/raw/tradingview/` from a
session that staged it, or wait for the EIA-API importer (milestone 2; it will supply actuals, not consensus).

```bash
python -m efie status                 # what is staged, first/last timestamp per series
```

## Research pipeline

```bash
python -m efie run-all                # everything below, in order (~2 minutes)

python -m efie diagnose               # coverage, roll reconstruction, release-time alignment → docs/evidence/diagnostics.json
python -m efie validate               # walk-forward forecasts + gate (1h, 4h, next session) → docs/evidence/validation.json
python -m efie hypotheses             # pre-registered event studies → docs/evidence/hypotheses.json
python -m efie backtest               # overlays vs reference baselines, after costs → docs/evidence/backtest.json
python -m efie evidence               # human-readable summary → docs/evidence/EVIDENCE.md
```

Your own MCL strategies (objective 4): export positions as CSV with columns `time,position` (ISO-8601 with offset
or Unix seconds; signed MCL contracts; each row = "from this time on, hold this position"). Put `daily` in the
file name for a daily strategy, otherwise it is treated as hourly:

```bash
python -m efie backtest --signals exports/mcl_trend_hourly.csv exports/mcl_swing_daily.csv
```

Costs are in `config/efie.toml` (`[costs]`); set the commission to the all-in figure on your statements.

## Hourly and daily reports

```bash
python -m efie report hourly                          # latest closed hour → reports/hourly/EFIE_hourly_<UTC>.md / .json, latest.md
python -m efie report daily                           # latest settled session → reports/daily/…
python -m efie report hourly --asof 2026-10-15T17:00Z --print    # replay any past hour, point-in-time
python -m efie report daily  --asof 2026-10-15T21:00Z --print
```

Each report includes: forecasts with the gate verdicts (climatology shown where not validated), market state,
latest EIA/API/Baker Hughes releases vs consensus, next scheduled releases, how the indicators fit together,
the thesis board, the catalyst log, data freshness, and what changed since the previous report.

Scheduling (on your machine, after the data refresh step), e.g. crontab in ET:

```cron
5 * * * 0-5   cd /path/to/kasper && .venv/bin/python -m efie report hourly
20 17 * * 1-5 cd /path/to/kasper && .venv/bin/python -m efie report daily && .venv/bin/python -m efie dashboard
```

## Dashboard (what Pine cannot ingest)

```bash
python -m efie dashboard              # → dashboard/index.html (self-contained; open in any browser)
```

## Standalone TradingView indicator

```bash
python -m efie pine-preview           # → dashboard/pine_preview.html and pine_preview_last50.csv
```

Open `dashboard/pine_preview.html` to see every series the indicator plots and the last-bar table values. To
run the real indicator: TradingView → open a **new chart tab** on `NYMEX:CL1!` (or `MCL1!`), 1-hour → Pine
Editor → *New* → *Indicator* → replace the template with the contents of `pine/KASPER_EFIE_Research.pine` →
*Save* (name it "KASPER EFIE Research") → *Add to chart*. Compare the indicator's table with the preview's
last-bar table. Your existing indicator and layouts are untouched.

Release times (EIA, API) — weekly:

```bash
python -m efie pine-schedule          # prints the schedule string and writes dashboard/pine_schedule.txt
```

Indicator settings → *Release schedule* → paste the string into "Schedule from EFIE". Bars from the first listed
time on are marked from the list (holiday shifts included); earlier bars use the Wed 10:30 / Tue 16:30 ET rule.
Entries on the usual weekday at an unusual time are flagged in the output (typically forward entries the
calendar has not yet adjusted for a daylight-saving change) — regenerate nearer the date.

Settings the indicator pins: futures are requested unadjusted with settlement as the daily close (the same series
the engine uses), whatever the chart's own continuous-futures settings are. z-scores in the indicator's table use
the chart's bars ("z (240 × 60)" = 240 one-hour bars, which matches the report's M1–M2 z); the report's crack
z uses 250 daily sessions — a 1D chart with lookback 250 matches it.

If TradingView rejects the `ticker.modify(… backadjustment …, settlement_as_close …)` line (older Pine runtimes),
replace the body of `pinned(sym)` with `sym` and keep the chart's continuous-futures settings at their defaults.

## Tests

```bash
python -m pytest                      # full suite; real-data checks skip when data/raw is empty
python -m pytest tests/test_point_in_time.py -v      # the no-look-ahead tests
```

## Catalyst log

Add one row per event to `config/catalysts.csv` **when you learn of it**, with `logged_at_utc` = now. Never
back-date `logged_at_utc`; that column is what keeps the log usable for back-tests later.
