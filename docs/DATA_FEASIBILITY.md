# Data-source feasibility (2026-10-20)

## Network reality in this environment

Outbound HTTPS is restricted by the environment's network policy. Every public energy-data host tested was
refused by the proxy (HTTP 403 on CONNECT):

`fred.stlouisfed.org`, `api.stlouisfed.org`, `alfred.stlouisfed.org`, `api.eia.gov`, `www.eia.gov`, `ir.eia.gov`,
`www.cftc.gov`, `publicreporting.cftc.gov`, `query1.finance.yahoo.com`, `stooq.com`, `www.cmegroup.com`,
`rigcount.bakerhughes.com`, `api.gdeltproject.org`, `www.balticexchange.com`, `www.tradingview.com`.

Package registries (PyPI, npm) are reachable. To use the public sources directly, add the hosts under
**Allowed domains** in the cloud environment's network settings (environment menu → Edit → Network access);
see <https://code.claude.com/docs/en/cloud-environments#network-access>. On your own machine none of this applies.

What *was* reachable is the **TradingView connector** attached to this session. Its results are saved to disk by
the tool host and staged byte-for-byte into `data/raw/tradingview/` with a SHA-256 manifest — no number was typed
by hand.

## Domain-by-domain

| Brief domain | Ideal source | Milestone 1 source (real) | Point-in-time quality | Status |
|---|---|---|---|---|
| WTI price, hourly | CME MDP 3.0 / Databento | TradingView `NYMEX:CL1!`, `CL2!`, `MCL1!` 1h, 2025-01-01 → 2026-10-20 (~10.6k bars) | Bars stamped at open; forming bars dropped | ✅ available, **short** (≈ 22 months, 93 EIA weeks) |
| WTI price, daily | CME settlements | `CL1!`, `CL2!` daily 2010 → now (close = 14:30 ET settlement; open = 18:00 ET) | Settlement vs decision timing handled (see METHODOLOGY) | ✅ |
| Term structure | Full CME curve | **M1–M2 only**. TradingView has no deeper continuous contracts (`CL3!`, `CL7!`, `CL13!` → invalid symbol) | — | ⚠️ partial: deeper curve needs individual contract months (milestone 2) |
| Diesel / gasoline cracks | NYMEX HO, RB | `HO1!`, `RB1!` hourly and daily | Product and crude front months roll on different days; change features masked across rolls | ✅ |
| Inventories | EIA WPSR + vintage history | Economic calendar: EIA crude, gasoline, distillate, Cushing, imports, production; API crude — **first-print actual, consensus and release timestamp**, 2015 → now (distillate/Cushing/runs from 2020; API from late 2017) | Genuine release timestamps; first prints; prior-week revisions visible at next release | ✅ the strongest PIT dataset available |
| Refinery activity | EIA WPSR (runs, utilisation) | EIA refinery crude runs change, gasoline/distillate production changes (2020 →) | as above | ⚠️ no utilisation % |
| Physical crude deliveries | CME delivery notices, Cushing pipeline flows | **Proxy only:** EIA Cushing stock changes; front-spread behaviour near expiry | — | ⚠️ proxy |
| Freight rates | Baltic Exchange (TD3C, TD25), Platts | NYMEX TD3C VLCC freight futures front month (`TL1!`, daily settlements 2010 → **2026-06-08**, then stale) and the BWET tanker-freight ETF (2023 →) | TL1 lagged one session; staleness > 5 days → missing | ⚠️ partial; TD3C **stale since June 2026** in this feed; TD25/TD22 futures too sparse to use |
| Vessel flows | Kpler, Vortexa, Kayrros | **none** | — | ❌ not modelled — nothing invented |
| Geopolitical catalysts | GDELT, licensed news, curated log | none historical; TradingView/Alpha Vantage news exist but not point-in-time over the history needed | — | ❌ for back-tests; a PIT-safe manual log (`config/catalysts.csv`) starts empty |
| Positioning (CFTC COT) | cftc.gov | blocked | — | ❌ (allow `www.cftc.gov` / `publicreporting.cftc.gov`) |
| Brent–WTI | ICE Brent | `ICEEUR:BRN1!` daily 2010 → now | lagged one session (ICE session ends after CME) | ✅ |

## Observations that shape the research

* **Coverage is complete week by week.** All 615 EIA crude releases from January 2015 are present. The three
  "missing" weeks are each followed by a week with two releases (EIA's delayed reports of June 2022,
  November 2023 and the December 2025 holiday) — genuine publication timing, kept as such.
* **Release times are aligned.** Standard releases sit at Wed 10:30 ET in both EST and EDT; holiday weeks at
  Thu 11:00/12:00 ET. Where the calendar time may be later than the true release (some holiday Thursdays), the
  error is conservative — data is treated as known later, never earlier.
* **API → EIA coherence.** The API surprise predicts the EIA surprise (ρ ≈ +0.69, n = 266) — the release data are
  internally consistent.
* **The continuous contract rolls two business days before CME last trade.** Reconstructed from session-open gaps
  (`docs/evidence/diagnostics.json`); April 2020 (roll on the last trading day) is correctly found as an exception.
* **2026 is an extreme regime.** CL traded 55–119 within the hourly sample, TD3C freight rose ~8× and BWET ~80×
  from mid-2025. Anything learned on 2015–2025 should be expected to be unstable here.

## What would most improve the evidence (in order)

1. **Minute-level CL/MCL bars around EIA/API releases** (Databento, CME DataMine, or IBKR historical bars). The
   inventory reaction is concentrated in the first minutes; hourly bars blur it (`S1` sanity check is flat).
2. **Longer hourly history** (2015 →) from the same vendor — 22 months is too short for hourly validation.
3. **Your MCL strategy position exports** — the only way to answer objective 4 about *your* strategies.
4. **EIA API key + network access** for full WPSR tables (utilisation, exports, SPR) and vintages.
5. **Freight**: a Baltic Exchange or Platts licence (TD3C, TD25 daily assessments), or at least a live TD3C
   futures feed; **vessel flows** from Kpler/Vortexa if physical-flow signals are a priority.
6. **CFTC COT** (allow the host) and a **licensed, timestamped news feed** for catalysts.
