# Implementation plan

## Principles

Research-only, point-in-time, pre-registered, after costs, and nothing promoted without out-of-sample evidence.
No change to the Command Desk, the risk governor, HARD LOCK, execution rules or your existing Pine indicator.

## Milestone 1 — delivered on this branch

| Objective | Delivered |
|---|---|
| 1. Hourly & daily research engine (freight, deliveries, refinery, cracks, curve, inventories, catalysts) | `efie/` package: provenance-tracked ingest, roll reconstruction, PIT feature frames for every domain the data genuinely supports; catalyst log (empty, PIT-safe) |
| 2. Probabilities, expected returns, intervals for 1h / 4h / next session — only where validated | Walk-forward forecasts + gate; reports fall back to climatology where the gate fails |
| 3. What changed, how indicators interact, what strengthens / invalidates a thesis | Report diffs, interaction readings, thesis board with historical test per thesis |
| 4. PIT out-of-sample tests vs MCL technical strategies after costs | Overlay harness with costs, rolls, stress costs, Holm; reference baselines; plug-in for your position exports |
| 5. Independent TradingView indicator + external dashboard | `pine/KASPER_EFIE_Research.pine` (new file), offline preview, static dashboard for what Pine can't ingest |

## Milestone 2 — proposed (needs your input or data)

1. **Reconcile with the brief** once it is available; adjust naming, thresholds and scope.
2. **Your strategies:** run `efie backtest --signals` on exports of your MCL strategies (positions over time).
3. **Minute data around releases** to test the inventory channel where it actually acts; event windows of
   5–60 minutes, with the same sanity checks.
4. **Deeper curve:** individual CL contract months (M1…M12) for curve shape (M1–M3, M1–M6, M1–M12, butterflies).
5. **Physical / freight:** live TD3C (or Baltic licence), TD25 USGC→UKC if a series becomes dense; vessel flows
   if licensed.
6. **Positioning and catalysts:** CFTC COT (allow host); a licensed timestamped news feed; start logging catalysts
   in `config/catalysts.csv` now so they accrue point-in-time history.
7. **Forward paper test:** register any candidate (e.g. the carry filter) in `HYPOTHESES.md`, then run the hourly
   and daily reports on a schedule and score them on data that arrives after registration.

## Milestone 3 — only if milestone 2 evidence passes

A read-only context panel in the Command Desk fed by EFIE's JSON (see `INTEGRATION_PROPOSAL.md`), behind the
gate, with no path into order logic, sizing, the risk governor or HARD LOCK. Your review and sign-off first.
