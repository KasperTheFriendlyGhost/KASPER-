# Repository audit (2026-10-20)

## What was asked for, and what exists

The request asked me to read `KASPER_V4_Energy_Intelligence_Claude_Code_Brief.md` in full and to inspect the
existing MCL Command Desk, prior research results, the risk-governor rules and the existing Pine indicator.

**None of these exist in anything this session can reach.** I searched:

| Where | Result |
|---|---|
| This repository, every branch (`main`, `native`, `ci-screenshots`, `claude/kasper-v4-efie-development-jbt8yo`) and full git history | No brief, no Command Desk, no Pine (`*.pine`) files, no research results, no risk-governor / HARD LOCK rules, no Python research code. |
| The whole container filesystem (`find / -iname '*KASPER*' -o -iname '*.pine' -o -iname '*governor*' …`) | Nothing relevant. |
| Other repositories available to this session (`list_repos`) | Only `KasperTheFriendlyGhost/CasinoGhost`. |

The repository is **CasinoGhost**, a blackjack trainer: a Rust engine (`engine/`), a native SwiftUI iOS/iPadOS app
(`apple/`), a React/Vite web app (`src/`), App Store material (`docs/app-store/`) and CI workflows
(`.github/workflows/apple.yml`, `ios.yml`, `pages.yml`). Nothing in it relates to crude oil, MCL, TradingView or
trading execution.

## Consequences for this milestone

1. **The brief was not read** because it is not available. Milestone 1 was built from the objectives and
   restrictions in your message. Anything in the brief that differs from them (data vendors, naming,
   architecture, thresholds) will need reconciling — please add the brief to the repository (for example as
   `kasper/docs/KASPER_V4_Energy_Intelligence_Claude_Code_Brief.md`) or paste it into the next session.
2. **"Your existing MCL technical strategies" could not be tested.** Objective 4 is implemented as a harness:
   your strategies plug in as position exports (`time,position` CSVs; see `RUNBOOK.md`). Until then, three
   *reference* baselines (EMA 20/50 and 24-bar Donchian on hourly bars, 20-day momentum on daily bars) exercise
   the same tests. Their results say nothing about your strategies.
3. **The risk governor, HARD LOCK and execution rules were not changed** — they are not here. EFIE has no order
   path, broker connection or alert, and reads nothing from the Command Desk.
4. **Your existing Pine indicator was not touched** — it is not here either. The EFIE indicator is a new,
   separate file (`kasper/pine/KASPER_EFIE_Research.pine`) to be added on a new chart tab.
5. **Existing files are preserved.** All new work is inside `kasper/`; no existing file in the repository was
   modified, and no CI workflow is triggered by this branch (`apple.yml` runs only on `main`/`native` with
   engine/app path filters; `pages.yml` only on `main`).

## Placement and visibility

The repository is **public**. Code and aggregate evidence are committed; **market data is not** (CME/ICE
prices via TradingView are licensed, and the consensus figures belong to the calendar provider). `kasper/.gitignore`
excludes `data/`, `reports/` and generated dashboard pages. If you would rather keep the research code private,
move `kasper/` to a private repository before merging.
