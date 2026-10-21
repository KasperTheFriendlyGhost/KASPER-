"""Markdown rendering of an EFIE report."""

from __future__ import annotations


def _pct(x, d=2):
    return "—" if x is None else f"{x * 100:+.{d}f}%"


def _num(x, fmt="{:.2f}"):
    return "—" if x is None else fmt.format(x)


def to_markdown(r: dict) -> str:
    m = r["market"]
    L = []
    title = "Hourly" if r["kind"] == "hourly" else "Daily"
    L.append(f"# KASPER V4 · EFIE {title} Report")
    L.append(f"As of **{r['asof_et']}** ({r['asof']} UTC). Data snapshot: {r['snapshot']}.")
    L.append("")
    L.append(f"> {r['disclaimer']}")
    L.append("")
    if r.get("changes"):
        L.append(f"## What changed since {r.get('previous_asof', 'the previous report')}")
        L += [f"- {c}" for c in r["changes"]]
        L.append("")
    L.append("## Forecasts")
    L.append("| Horizon | P(up) | Expected return | 80% interval (return) | 80% interval (CL price) | Gate: direction / return / interval |")
    L.append("|---|---|---|---|---|---|")
    for f in r["forecasts"]:
        s, g = f["shown"], f["gate"]["components"]
        v = " / ".join(g.get(c, {}).get("verdict", "—") for c in ("direction", "expected_return", "interval"))
        ip = s["interval_prices"]
        L.append(
            f"| {f['horizon']} | {_num(s['p_up'], '{:.3f}')} ({s['p_up_source']}) | {_pct(s['expected_return'], 3)} ({s['expected_return_source']}) "
            f"| {_pct(s['interval'][0])} … {_pct(s['interval'][1])} ({s['interval_source']}) | {_num(ip[0])} … {_num(ip[1])} | {v} |"
        )
    L.append("")
    for f in r["forecasts"]:
        L.append(f"**{f['horizon']} gate** (out-of-sample forecasts made before this time: {f['gate'].get('n_oos', '—')}):")
        for c, x in f["gate"]["components"].items():
            L.append(f"- {c}: **{x['verdict']}** — {x['reason']}")
        raw = f["efie_model_raw"]
        L.append(f"- EFIE model raw output (not used unless validated): P(up) {_num(raw['p_up'], '{:.3f}')}, expected {_pct(raw['expected_return'], 3)}")
    L.append("")
    L.append("## Market state")
    L.append("| | Value | |")
    L.append("|---|---|---|")
    L.append(f"| CL1 last (bar {m['cl1_bar']}) | {_num(m['cl1_last'])} | 1h {_pct(m['ret_1h'])}, 4h {_pct(m['ret_4h'])}, 24h {_pct(m['ret_24h'])} |")
    L.append(f"| CL1 settle ({m['settle_date']}) | {_num(m['cl1_settle'])} | 1d {_pct(m['ret_1d'])}, 5d {_pct(m['ret_5d'])} |")
    L.append(f"| M1–M2 spread (USD/bbl) | {_num(m['spread12'], '{:+.2f}')} | {m['regime']}; z (240 hourly bars) {_num(m['spread12_z'], '{:+.2f}')}; 5-session Δ {_num(m['spread12_chg5'], '{:+.2f}')} |")
    L.append(f"| 3-2-1 crack (USD/bbl) | {_num(m['crack321'])} | z (250 sessions) {_num(m['crack321_z'], '{:+.2f}')}; diesel {_num(m['crack_diesel'])}, gasoline {_num(m['crack_gas'])} |")
    L.append(f"| Brent–WTI (USD/bbl, lagged 1 session) | {_num(m['brent_wti'], '{:+.2f}')} | 5-session Δ {_num(m['brent_wti_chg5'], '{:+.2f}')} |")
    td3c = "STALE / unavailable" if m["td3c_chg5"] is None else f"{_num(m['td3c'])} USD/mt, 5d {_pct(m['td3c_chg5'], 1)}"
    L.append(f"| TD3C VLCC freight | {td3c} | last obs {_num(m['td3c_age_days'], '{:.0f}')} days old |")
    L.append(f"| BWET tanker-freight ETF | 5d {_pct(m['bwet_chg5'], 1)} | |")
    L.append(f"| Realised vol (24h, annualised) | {_pct(m['vol_24h_annualised'], 1)} | |")
    L.append("")
    L.append("## Inventories and refinery activity (latest published)")
    L.append("| Series | Released (UTC) | Period | Actual | Consensus | Surprise (z) | vs prior 52 (z) | vs 5-yr same week |")
    L.append("|---|---|---|---|---|---|---|---|")
    for s, x in r["fundamentals"]["latest"].items():
        L.append(
            f"| {s} | {x['release_ts'][:16]} | {x['period']} | {_num(x['actual'], '{:,.0f}')} | {_num(x['consensus'], '{:,.0f}')} "
            f"| {_num(x['surprise_z'], '{:+.2f}')} | {_num(x['change_z'], '{:+.2f}')} | {_num(x['seasonal_dev'], '{:+,.0f}')} |"
        )
    if r["fundamentals"]["next_scheduled"]:
        L.append("")
        L.append("Next scheduled: " + "; ".join(f"{x['series']} {x['release_et'][:16]} ET" + (f" (consensus {x['consensus']:,.0f})" if x["consensus"] is not None else "") for x in r["fundamentals"]["next_scheduled"]))
    L.append("")
    L.append("## How the indicators fit together")
    L += [f"- {x}" for x in r["interpretations"]] or ["- No combination rule fired."]
    L.append("")
    L.append("## Thesis board")
    for t in r["theses"]:
        L.append(f"### {t['id']} · {t['title']} — **{t['status']}** ({t['label']})")
        L.append(f"{t['claim']} *Implies: {t['lean']}.*")
        for o in t["observations"]:
            val = o.get("display", "missing")
            L.append(f"- {o['label']}: {val} → {o['state']}")
        for e in t["evidence"]:
            ci = e["ci"]
            L.append(f"- History: {e['id']}: ρ {e['rho']:+.3f} (95% CI {ci[0]:+.3f} … {ci[1]:+.3f}, n={e['n']}), {'significant' if e['significant_after_holm'] else 'not significant'} after Holm")
        L.append("")
    L.append("## Catalyst log (point-in-time; entries known by this time)")
    if r.get("catalysts"):
        for c in r["catalysts"]:
            L.append(f"- [{c['category']}] {c['region']}: {c['description']} (logged {c['logged_at_utc']}; {c['source_url']})")
    else:
        L.append("- No active entries. The log starts empty — nothing is back-filled (see `config/catalysts.csv`).")
    L.append("")
    L.append("## Data freshness")
    L.append("| Source | Last | Age (h) | Status |")
    L.append("|---|---|---|---|")
    for x in r["freshness"]:
        L.append(f"| {x['source']} | {x['last']} | {_num(x['age_hours'], '{:.1f}')} | {x['status']} |")
    return "\n".join(L) + "\n"
