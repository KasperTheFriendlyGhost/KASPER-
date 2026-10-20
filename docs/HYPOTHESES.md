# Pre-registered hypotheses (milestone 1)

Written before the tests were run (except where marked *post hoc*). Each is a Spearman rank correlation between a
quantity known at decision time and an outcome that resolves strictly afterwards, with a moving-block bootstrap
95% CI. The **tradeable family** (H1–H10) is Holm–Bonferroni adjusted at α = 0.05. Sanity checks are excluded
from the family: they measure reactions *inside* the release bar or session, which cannot be traded, and exist to
show the data and timestamps line up. Results: `docs/evidence/EVIDENCE.md` §2.

## Sanity checks (not tradeable)

| ID | Question | Expected |
|---|---|---|
| S1 | Does the hourly bar containing the EIA release move against the crude surprise (actual − consensus)? | ρ < 0 |
| S2 | Does the hourly bar containing the API release move against the API crude change? | ρ < 0 |
| S3 | Does the release-day session (18:00 ET open → 14:30 ET settle) move against the crude surprise? | ρ < 0 |
| S4 *(post hoc)* | Prior settlement → release-day settlement (this window includes the API reaction the evening before). | ρ < 0 |
| S5 *(post hoc)* | Does the EIA figure's deviation from the API figure move the release-day session against it? | ρ < 0 |

S4 and S5 were added after S1–S3 came back weak, to diagnose *why* (the API report lands in the overnight gap
before the EIA session). They are diagnostics, not evidence for any signal.

## Tradeable family

| ID | Decision time | Predictor | Outcome |
|---|---|---|---|
| H1 | close of the EIA release bar | EIA crude surprise (z) | next 1 h return |
| H2 | close of the EIA release bar | EIA crude surprise (z) | next 4 h return |
| H3 | release-day 17:00 ET | EIA crude surprise (z) | next session (open → settle) |
| H4 | API release | API crude surprise (z) | EIA crude surprise (z) the next day |
| H5 | close of the API release bar | API crude change (z) | return until the bar before EIA |
| H6 | EIA release day | Cushing change (z) | M1–M2 spread change over the next 5 sessions |
| H7 | 17:00 ET | 3-2-1 crack 5-session change | next session |
| H8 | 17:00 ET | M1–M2 spread as % of price | next session |
| H9 | 17:00 ET | TD3C freight 5-day log change (lagged 1 session) | Brent–WTI change over next 5 sessions |
| H10 | 17:00 ET | TD3C freight 5-day log change (lagged 1 session) | next session |

## Pre-registered model comparison

`clim` (unconditional) vs `tech` (price-only features) vs `tech_fund` (technical + term structure, cracks,
inventories, refinery runs, freight, Brent–WTI). Fixed hyperparameters (`config/efie.toml [validation]`): L2
logistic C = 0.05, ridge α = 50, split-conformal 80% intervals. The question "do fundamentals add value?" is
`tech_fund` vs `tech`, by paired Brier difference — not "which model looks best".

## Pre-registered overlays

`eia_standaside`, `efie_agreement`, `carry_filter` on every baseline, compared over the EFIE out-of-sample
window, Holm-adjusted across all overlay × baseline tests.

## Rule for anything new

Any new predictor, model or overlay is added to this file *before* it is run, joins the Holm family, and is
judged on data that arrives after it was registered (forward paper test) before it can be called validated.
