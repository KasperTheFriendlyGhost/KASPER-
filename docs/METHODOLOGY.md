# Methodology

## 1. Point-in-time discipline

Every observation carries `available_ts`, the earliest moment it could have been known. A decision at time `τ`
sees only observations with `available_ts ≤ τ` (`efie/features/asof.py` is the only place the rule is applied).

| Data | `available_ts` |
|---|---|
| Hourly bar opening at `t` | `t + 1h` (bar close); forming bars dropped using the snapshot time |
| CME daily bar for trading date `D` (CL, RB, HO) | 17:00 ET on `D` |
| ICE Brent daily, TD3C freight futures | 17:00 ET on the **next** business day (session timing uncertain → lag one) |
| BWET daily close | 16:05 ET on that date, and only once the session is complete |
| EIA / API / Baker Hughes release | stated release timestamp + 5 minutes |
| Catalyst log entry | `logged_at_utc` (when it was written down), never earlier |

Release standardisation uses only earlier releases: surprise z = (actual − consensus) ÷ s.d. of the previous 52
surprises; change z against the previous 52 actuals; seasonal deviation against the same ISO week ±1 of the
previous five years.

**Tested, not assumed:** `tests/test_point_in_time.py` rebuilds every feature from data truncated at time T and
requires every row decided at or before T to be identical to the full-history build — on a synthetic market and
on the real snapshot. This test caught one real inconsistency during development (a partly traded ETF day was
briefly treated as a daily close); it was fixed before any evidence was produced.

## 2. Contract rolls

`CL1!` is unadjusted. Rolls are reconstructed from session-open gaps (the new front month opens next to where it
closed as the second month) inside a window fixed by the CME contract calendar (`LTD−4 … LTD+1` business days),
requiring the M1–M2 spread to exceed twice the typical recent gap. Undetectable months (narrow spreads) default
to the vendor's observed convention, LTD − 2 business days; their windows are flagged `roll_uncertain` and the
daily backtests are also reported excluding them. Returns across a roll use the new contract's previous price
(`log(F_t / S_{t−1})`). Product (RB/HO) front months roll at month-end; crack *changes* are masked across any
roll of either leg.

## 3. Targets and fills

* **1h / 4h:** contract-consistent log return from the decision bar's close to the close `h` bars later, valid only
  if the span is `h` hours of trading (the 17:00–18:00 ET halt allowed; weekends excluded).
* **Next session:** the daily close is the **14:30 ET settlement**, so a decision at the 17:00 ET close (which may
  use, e.g., the 16:30 ET API report) cannot be filled at it. The target is the next session from its 18:00 ET
  open to its settlement; in backtests the settle → open gap accrues to the position already held.

## 4. Models and validation

* Purged expanding-window walk-forward: training rows must have targets that resolved before the first test
  decision; test blocks never overlap. Hourly: first forecast after 2,000 bars, refit every 250. Daily: after 750
  sessions, refit every 63.
* `clim`: unconditional P(up) and mean; intervals from vol-normalised return quantiles.
* `tech` / `tech_fund`: L2 logistic (P(up)) and ridge (vol-normalised return) on standardised, clipped features
  (scaler fit on training data only); split-conformal intervals on vol-normalised residuals.
* Scores: Brier skill vs climatology, log loss, AUC, calibration gap, reliability bins, OOS R², interval coverage
  and width, by year. CIs from a moving-block bootstrap (24 h blocks hourly, 10 sessions daily; at least 6× the
  horizon for overlapping targets).

## 5. The gate (what reports may show)

| Component | Shown as a model forecast only if (out of sample) |
|---|---|
| Direction, P(up) | n ≥ 1,500 (hourly) / 500 (daily); Brier-skill 95% CI lower bound > 0; calibration gap ≤ 0.02 |
| Expected return | OOS R² 95% CI lower bound > 0 |
| Prediction interval | coverage within ±0.05 of nominal (0.80) **and** a Winkler interval score no worse than the climatological interval's (otherwise the climatological interval is shown, with its own measured coverage) |

Otherwise the report shows the climatological value and states why. In a replayed report the gate is recomputed
from the forecasts made before that time.

## 6. Backtests

One MCL contract (100 bbl). Hourly: fill at the decision bar's close. Daily: fill at the next 18:00 ET open.
Costs per side: commission (default $1.25, set yours in `config/efie.toml`) + 1 tick ($1.00) slippage; a position
carried through a roll pays a round trip; all results repeated at 2× costs. Overlay vs baseline: mean session P&L
difference and Sharpe difference with block-bootstrap CIs; one-sided p-values Holm-adjusted across the family.
EFIE does not model your risk governor or HARD LOCK; any integration must be re-evaluated through them.

## 7. Explanations

* **What changed:** each report is diffed against the previous one (previous hour / previous session): prices,
  curve regime, new releases with surprise and prior-week revision, thesis status changes, gate changes, data
  freshness changes.
* **How indicators interact:** rule-based readings (e.g. crude draw + runs up → demand-led; crude draw + imports
  down → supply/logistics-led; product builds + weaker crack → margin pressure; Cushing draw vs prompt spread).
* **Thesis board:** five named theses with explicit strengthening and invalidating observations, each carrying
  its historical test. A thesis is labelled "historically supported" only if its test survived Holm; otherwise
  "hypothesis — not a validated signal", whatever commentary says.
