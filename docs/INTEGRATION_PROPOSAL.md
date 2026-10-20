# Integration proposal — draft for your review

**Status:** proposal only. Nothing has been added to the MCL Command Desk, and nothing will be without your
explicit sign-off. EFIE has no connection to the Desk, the risk governor, HARD LOCK or any order path.

## Recommendation

**Do not integrate any EFIE forecast, filter or signal into live MCL decision-making at this stage.**

The milestone-1 evidence (`docs/evidence/EVIDENCE.md`) does not support it:

| Question | Evidence | Verdict |
|---|---|---|
| Do EFIE probabilities beat climatology? | Brier skill of the EFIE model is negative at 1h (−0.018), 4h (−0.052) and next session (−0.031), with 95% CIs entirely below zero | No — worse than climatology |
| Do fundamentals add to technical information? | Paired Brier difference `tech_fund` − `tech` negative at all three horizons (CIs below zero) | No — they hurt as specified |
| Is any expected-return forecast usable? | OOS R² CIs never above zero | No |
| Do any pre-registered relationships hold? | Only API → EIA surprise (ρ ≈ +0.69), which is informational (the API report precedes EIA), not a price signal; no drift after EIA (H1–H3), no Cushing/crack/curve/freight effect (H6–H10) | No tradeable relationship |
| Do the overlays improve the (reference) strategies after costs? | No overlay significant after Holm; the EFIE-agreement filter is worse (turnover up to ×4 on the hourly baselines); EIA stand-aside neutral to negative | No |
| Is anything validated? | The **volatility-scaled climatological 80% range** is calibrated (coverage 0.796–0.799). It is not a fundamental signal. | Context only |

Caveats that cut both ways: the hourly sample is short (≈ 22 months) and 2026 is an extreme regime; the
inventory channel acts within minutes and hourly bars blur it; and the tests ran on reference baselines, not
your strategies. "No evidence" here is not proof that no fundamental edge exists — it is a reason not to act yet.

## What could be integrated now, if you want it (read-only context, optional)

A **context panel** in the Desk, fed by EFIE's JSON output, showing information only:

1. Scheduled EIA (Wed 10:30 ET), API (Tue 16:30 ET) and Baker Hughes times, and the last release vs consensus;
2. data freshness (e.g. TD3C freight stale since 2026-06-08);
3. the calibrated volatility range for 1h / 4h / next session (labelled "volatility range, not a forecast");
4. the thesis board, labelled "hypotheses — not validated signals".

Interface: the Desk *reads* `kasper/reports/hourly/latest.json` (keys `forecasts[].shown`, `forecasts[].gate`,
`fundamentals.latest`, `fundamentals.next_scheduled`, `theses`, `freshness`, `changes`). EFIE writes nothing to
the Desk; the panel has no inputs into order entry, sizing, the risk governor or HARD LOCK, and is behind a
feature flag that defaults off.

## Candidate for forward paper-testing (not integration)

The **carry filter** (keep longs only in backwardation, shorts only in contango) had positive point estimates on
all three reference baselines (ΔSharpe +0.15 to +0.61) but every CI includes zero. If you want to pursue it:

1. run it on **your** strategy exports first (`efie backtest --signals …`);
2. if still promising, register it with a success criterion in `HYPOTHESES.md` (e.g. forward ΔSharpe CI lower
   bound > 0 after costs, at least three months of new data, evaluated through a simulation of your governor);
3. paper-trade it alongside the Desk — no live orders — until the criterion is met or fails.

## Preconditions for any future signal integration

* the forecast or overlay passes the EFIE gate on data that arrived **after** it was registered;
* it improves **your** strategies after costs, tested through your risk governor and HARD LOCK rules;
* it can only make the Desk **more conservative** (stand aside, smaller size) — never larger, never overriding a
  lock;
* a kill switch and a feature flag that defaults off;
* your review of this document, updated with that evidence, and your sign-off.
