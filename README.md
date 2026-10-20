# KASPER V4 · Energy Fundamental Intelligence Engine (EFIE)

A Python research engine for WTI/MCL that asks one question before anything else: **does this information
improve a forecast, out of sample, point-in-time, after costs?** It is research-only. It has no connection to
the MCL Command Desk, the risk governor, HARD LOCK or any order path, and it does not touch your existing Pine
indicator.

> **Milestone 1 result, in one line:** with the data genuinely available here, no fundamental feature, model or
> overlay showed out-of-sample value after costs and multiple-testing correction; the only calibrated output is
> a volatility-scaled range. The engine therefore shows climatology wherever its gate fails — which, today, is
> everywhere. Details: [`docs/evidence/EVIDENCE.md`](docs/evidence/EVIDENCE.md).

## Read first

| Document | What it covers |
|---|---|
| [`docs/AUDIT.md`](docs/AUDIT.md) | What exists in this repository (the brief, Command Desk, Pine indicator and risk-governor rules do not) |
| [`docs/DATA_FEASIBILITY.md`](docs/DATA_FEASIBILITY.md) | Every data domain: what is real, what is a proxy, what is missing, what to add |
| [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) | Milestones 1 (done), 2 and 3 |
| [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) | Point-in-time rules, rolls, targets and fills, models, the gate, backtests, explanations |
| [`docs/HYPOTHESES.md`](docs/HYPOTHESES.md) | Pre-registered tests |
| [`docs/evidence/EVIDENCE.md`](docs/evidence/EVIDENCE.md) | The backtest and validation evidence |
| [`docs/INTEGRATION_PROPOSAL.md`](docs/INTEGRATION_PROPOSAL.md) | Draft for your review: what (not) to add to the Command Desk |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Exact commands |

## Quick start

```bash
cd kasper
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m efie status            # needs staged data (see RUNBOOK: data is licensed and not in git)
python -m efie run-all           # diagnostics → validation → hypotheses → backtests → reports → dashboard → Pine preview → evidence
python -m efie report hourly --print
python -m efie report daily --print
python -m pytest
```

## Layout

```
kasper/
  config/efie.toml              costs, PIT rules, validation and gate thresholds (all assumptions in one place)
  config/catalysts.csv          point-in-time catalyst log (starts empty; nothing back-filled)
  efie/ingest/                  staging with SHA-256 provenance, TradingView result parsers, CSV import
  efie/market/                  CME sessions, contract calendar, roll reconstruction, consistent returns
  efie/features/                as-of joins, inventory surprises, hourly/daily decision frames, catalysts
  efie/models/                  climatology and regularised linear forecasters with conformal intervals
  efie/validation/              purged walk-forward, metrics, gate, hypotheses, diagnostics
  efie/backtest/                MCL P&L with costs and rolls, reference baselines, overlays, your signal loader
  efie/explain/                 thesis board and indicator-interaction readings
  efie/reports/                 hourly/daily reports, dashboard, Pine preview, evidence summary
  pine/KASPER_EFIE_Research.pine   standalone research indicator (new file; research only, no alerts)
  tests/                        point-in-time, market, validation, backtest, ingest/output tests
  docs/                         the documents above; docs/evidence/ holds aggregate results only
  data/ reports/ dashboard/     generated, gitignored (licensed market data stays out of git)
```
