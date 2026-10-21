"""Static research dashboard for what Pine Script cannot ingest.

TradingView's Pine can read prices but not EIA/API figures against consensus, freight
futures that the chart symbol doesn't carry, the thesis board, or the validation and
backtest evidence. This page shows those, generated from the latest reports and evidence
files into one self-contained HTML file (no server, no external requests).
"""

from __future__ import annotations

import html
import json

import numpy as np
import pandas as pd

from efie.features.build import MarketData, _daily_obs, build_daily
from efie.config import load_config
from efie.paths import DASHBOARD_DIR, EVIDENCE_DIR, REPORTS_DIR
from efie.reports.htmlkit import BASE_CSS, CHART_JS


def _series(dates, values) -> list[list]:
    out = []
    for d, v in zip(dates, values):
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            continue
        out.append([str(pd.Timestamp(d).date()), round(float(v), 4)])
    return out


def _chart_data(md: MarketData, cfg: dict) -> dict:
    d = build_daily(md, cfg).iloc[-250:]
    obs = _daily_obs(md, cfg)
    charts = {
        "cl1": {"title": "WTI front month (CL1) settlement", "unit": "USD/bbl", "data": _series(d.index, d["close"])},
        "spread": {"title": "M1–M2 spread (backwardation > 0)", "unit": "USD/bbl", "zero": True, "data": _series(d.index, d["ts_spread12"])},
        "crack": {"title": "3-2-1 crack spread", "unit": "USD/bbl", "data": _series(d.index, d["crk_321"])},
        "arb": {"title": "Brent–WTI spread", "unit": "USD/bbl", "data": _series(d.index, d["arb_brent_wti"])},
    }
    if "TL1" in obs:
        t = obs["TL1"].iloc[-250:]
        charts["td3c"] = {"title": "TD3C VLCC freight futures (front month)", "unit": "USD/mt", "data": _series(t["date"], t["close"])}
    if "BWET" in obs:
        b = obs["BWET"].iloc[-250:]
        charts["bwet"] = {"title": "BWET tanker-freight ETF", "unit": "USD", "data": _series(b["date"], b["close"])}
    ev = md.events[(md.events["series"] == "eia_crude") & md.events["actual"].notna()].tail(26)
    bars = []
    for _, r in ev.iterrows():
        if pd.notna(r["consensus"]):
            bars.append([str(r["release_ts"].date()), round((r["actual"] - r["consensus"]) / 1e6, 3)])
    charts["eia"] = {"title": "EIA crude stocks: actual − consensus (last 26 releases)", "unit": "M bbl", "bars": bars}
    return charts


def _load(path):
    return json.loads(path.read_text()) if path.exists() else None


def _status_chip(verdict: str) -> str:
    ok = verdict == "VALIDATED"
    cls = "good" if ok else "critical"
    icon = "✓" if ok else "✕"
    return f'<span class="chip {cls}"><span aria-hidden="true">{icon}</span> {html.escape(verdict)}</span>'


def _fmt(x, f="{:+.3f}"):
    return "—" if x is None else f.format(x)


def build_dashboard(md: MarketData, cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    hourly = _load(REPORTS_DIR / "hourly" / "latest.json")
    daily = _load(REPORTS_DIR / "daily" / "latest.json")
    val = _load(EVIDENCE_DIR / "validation.json")
    bt = _load(EVIDENCE_DIR / "backtest.json")
    hyp = _load(EVIDENCE_DIR / "hypotheses.json")
    charts = _chart_data(md, cfg)
    rep = daily or hourly or {}
    e = html.escape

    # Forecast / gate rows
    fc_rows = []
    for r in (hourly, daily):
        for f in (r or {}).get("forecasts", []):
            s, g = f["shown"], f["gate"]["components"]
            fc_rows.append(
                f"<tr><td>{e(f['horizon'])}</td><td class='num'>{_fmt(s['p_up'], '{:.3f}')}<div class='sub'>{e(s['p_up_source'])}</div></td>"
                f"<td class='num'>{_fmt(s['interval_prices'][0], '{:.2f}')} – {_fmt(s['interval_prices'][1], '{:.2f}')}<div class='sub'>{e(s['interval_source'])}</div></td>"
                + "".join(f"<td>{_status_chip(g.get(c, {}).get('verdict', '—'))}<div class='sub'>{e(g.get(c, {}).get('reason', ''))}</div></td>" for c in ("direction", "expected_return", "interval"))
                + "</tr>"
            )
    # Releases
    rel_rows = []
    for s, x in rep.get("fundamentals", {}).get("latest", {}).items():
        rel_rows.append(
            f"<tr><td>{e(s)}</td><td>{e(x['release_ts'][:16])}</td><td class='num'>{_fmt(x['actual'], '{:,.0f}')}</td>"
            f"<td class='num'>{_fmt(x['consensus'], '{:,.0f}')}</td><td class='num'>{_fmt(x['surprise_z'], '{:+.2f}')}</td><td class='num'>{_fmt(x['seasonal_dev'], '{:+,.0f}')}</td></tr>"
        )
    nxt = "; ".join(f"{e(x['series'])} {e(x['release_et'][:16])} ET" for x in rep.get("fundamentals", {}).get("next_scheduled", []))
    # Theses
    th = []
    for t in rep.get("theses", []):
        obs = "".join(f"<li>{e(o['label'])}: <b>{e(o.get('display', 'n/a'))}</b> <span class='muted'>({e(o['state'])})</span></li>" for o in t["observations"])
        evd = "".join(
            f"<li class='muted'>{e(x['id'])}: ρ {x['rho']:+.3f} [{x['ci'][0]:+.3f}, {x['ci'][1]:+.3f}], n={x['n']} — {'significant' if x['significant_after_holm'] else 'not significant'} after Holm</li>"
            for x in t["evidence"]
        )
        th.append(f"<div class='card'><h3>{e(t['id'])} · {e(t['title'])} <span class='tag'>{e(t['status'])}</span></h3><p class='sub'>{e(t['claim'])} Implies: {e(t['lean'])}. <i>{e(t['label'])}</i></p><ul>{obs}{evd}</ul></div>")
    # Backtests
    bt_rows = []
    for k, t in (bt or {}).get("tests", {}).items():
        sig = "good" if t["significant_after_holm"] else "critical"
        bt_rows.append(
            f"<tr><td>{e(k)}</td><td class='num'>{t['mean_diff_usd_per_session']:+.2f}</td><td class='num'>[{t['ci'][0]:+.2f}, {t['ci'][1]:+.2f}]</td>"
            f"<td class='num'>{t['sharpe_diff']:+.2f}</td><td class='num'>{t['p_holm']:.3f}</td><td><span class='chip {sig}'>{'✓ yes' if t['significant_after_holm'] else '✕ no'}</span></td></tr>"
        )
    hy_rows = []
    for grp in ("sanity", "family"):
        for k, t in (hyp or {}).get(grp, {}).items():
            flag = "—" if grp == "sanity" else ("✓" if t.get("significant_after_holm") else "✕")
            hy_rows.append(
                f"<tr><td>{e(k)}{' (post hoc)' if t.get('post_hoc') else ''}</td><td>{e(t.get('question', ''))}</td><td class='num'>{t['n']}</td>"
                f"<td class='num'>{_fmt(t['rho'])}</td><td class='num'>[{_fmt(t['ci'][0])}, {_fmt(t['ci'][1])}]</td><td>{flag}</td></tr>"
            )
    fr_rows = "".join(
        f"<tr><td>{e(x['source'])}</td><td>{e(str(x['last']))}</td><td><span class='chip {'good' if x['status'] == 'OK' else 'critical'}'>{'✓' if x['status'] == 'OK' else '!'} {e(x['status'])}</span></td></tr>"
        for x in rep.get("freshness", [])
    )
    interp = "".join(f"<li>{e(x)}</li>" for x in rep.get("interpretations", []))
    changes = "".join(f"<li>{e(x)}</li>" for x in (hourly or {}).get("changes", []))
    m = rep.get("market", {})
    hero = f"{m.get('cl1_last', 0):.2f}" if m.get("cl1_last") else "—"

    page = TEMPLATE.replace("__CSS__", BASE_CSS).replace("__CHART_JS__", CHART_JS).replace("__DATA__", json.dumps(charts)).replace("__ASOF__", e(str((hourly or rep).get("asof_et", ""))))
    page = page.replace("__HERO__", hero).replace("__REGIME__", e(m.get("regime", "—")))
    page = page.replace("__FC_ROWS__", "".join(fc_rows)).replace("__REL_ROWS__", "".join(rel_rows)).replace("__NEXT__", nxt or "—")
    page = page.replace("__THESES__", "".join(th)).replace("__BT_ROWS__", "".join(bt_rows)).replace("__HY_ROWS__", "".join(hy_rows))
    page = page.replace("__FR_ROWS__", fr_rows).replace("__INTERP__", interp or "<li>No combination rule fired.</li>").replace("__CHANGES__", changes or "<li>—</li>")
    page = page.replace("__DISCLAIMER__", e(rep.get("disclaimer", "")))
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    out = DASHBOARD_DIR / "index.html"
    out.write_text(page)
    return str(out)


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EFIE Research Dashboard</title>
<style>__CSS__</style></head><body><main>
<header><div><h1>KASPER V4 · EFIE research dashboard</h1><div class="sub">As of __ASOF__ · research only — not connected to the Command Desk, risk governor, HARD LOCK or execution</div></div>
<div><div class="sub">CL1 last</div><div class="hero">__HERO__</div><div class="sub">curve: __REGIME__</div></div></header>
<p class="note">__DISCLAIMER__</p>
<h2>Forecasts and validation gate</h2>
<div class="card scroll"><table><thead><tr><th>Horizon</th><th>P(up) shown</th><th>80% interval (CL)</th><th>Direction</th><th>Expected return</th><th>Interval</th></tr></thead><tbody>__FC_ROWS__</tbody></table></div>
<h2>Market structure</h2><div class="grid" id="charts"></div>
<h2>Inventories and refinery activity</h2>
<div class="grid"><div class="card" id="eia"></div><div class="card scroll"><table><thead><tr><th>Series</th><th>Released (UTC)</th><th>Actual</th><th>Consensus</th><th>Surprise z</th><th>vs 5-yr week</th></tr></thead><tbody>__REL_ROWS__</tbody></table><p class="sub">Next scheduled: __NEXT__</p></div></div>
<h2>What changed in the last hour</h2><div class="card"><ul>__CHANGES__</ul></div>
<h2>How the indicators fit together</h2><div class="card"><ul>__INTERP__</ul></div>
<h2>Thesis board</h2><div class="grid">__THESES__</div>
<h2>Overlay backtests vs reference baselines (after costs)</h2>
<div class="card scroll"><table><thead><tr><th>Baseline :: overlay</th><th>Δ USD/session</th><th>95% CI</th><th>Δ Sharpe</th><th>Holm p</th><th>Significant</th></tr></thead><tbody>__BT_ROWS__</tbody></table>
<p class="sub">Reference baselines are not your MCL strategies; supply your own signal exports to test those.</p></div>
<h2>Pre-registered hypothesis tests</h2>
<div class="card scroll"><table><thead><tr><th>Test</th><th>Question</th><th>n</th><th>ρ</th><th>95% CI</th><th>Holm</th></tr></thead><tbody>__HY_ROWS__</tbody></table></div>
<h2>Data freshness</h2><div class="card scroll"><table><thead><tr><th>Source</th><th>Last</th><th>Status</th></tr></thead><tbody>__FR_ROWS__</tbody></table></div>
</main><div class="tt" id="tt"></div>
<script>
const DATA=__DATA__;
__CHART_JS__const host=document.getElementById('charts');['cl1','spread','crack','arb','td3c','bwet'].forEach(k=>{if(!DATA[k])return;const c=document.createElement('div');c.className='card';host.appendChild(c);line(c,DATA[k])});
bars(document.getElementById('eia'),DATA.eia);
</script></body></html>
"""
