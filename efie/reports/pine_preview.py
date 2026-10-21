"""Preview the standalone Pine indicator without TradingView.

Computes, from the cached hourly data, exactly what ``pine/KASPER_EFIE_Research.pine``
plots on a 1-hour CL1! chart: M1–M2 spread, 3-2-1 / diesel / gasoline cracks,
previous-session Brent–WTI, the freight proxy's 5-session change, and z-scores using
Pine's ``ta.stdev`` (population standard deviation). The page also lists the last bar's
table values so they can be compared one-for-one with the indicator's table.

Known differences from TradingView: around session boundaries the "previous completed
session" for Brent and BWET can differ by one session (TradingView maps each chart bar to
the other symbol's own daily bars); bars where a symbol has no print are dropped here.
"""

from __future__ import annotations

import html
import json

import numpy as np
import pandas as pd

from efie.features.build import MarketData
from efie.market.sessions import ET, hourly_trading_date
from efie.paths import DASHBOARD_DIR
from efie.reports.htmlkit import BASE_CSS, CHART_JS

Z_LEN = 240


def pine_z(x: pd.Series, n: int = Z_LEN) -> pd.Series:
    mu = x.rolling(n).mean()
    sd = x.rolling(n).std(ddof=0)  # Pine ta.stdev(biased=true)
    return ((x - mu) / sd).where(sd > 0)


def compute(md: MarketData) -> pd.DataFrame:
    h = md.hourly
    idx = h["CL1"].index
    m1, m2 = h["CL1"]["c"], h["CL2"]["c"].reindex(idx)
    rb, ho = h["RB1"]["c"].reindex(idx), h["HO1"]["c"].reindex(idx)
    df = pd.DataFrame(index=idx)
    df["spread12"] = m1 - m2
    df["crack321"] = (2 * rb * 42 + ho * 42 - 3 * m1) / 3
    df["crack_diesel"] = ho * 42 - m1
    df["crack_gas"] = rb * 42 - m1
    td = hourly_trading_date(idx)
    wti_d = md.daily["CL1"]["c"]
    br_d = md.daily["BRN1"]["c"]
    prev = lambda s: pd.Series(s.shift(1).reindex(td, method="ffill").to_numpy(), index=idx)  # noqa: E731
    df["brent_wti_prev"] = prev(br_d.reindex(wti_d.index, method="ffill")) - prev(wti_d)
    bw = h["BWET"]
    if len(bw):
        bw_d = bw["c"].groupby(pd.DatetimeIndex(bw.index.tz_convert(ET).date.astype("datetime64[ns]"))).last()
        chg = np.log(bw_d.shift(1) / bw_d.shift(6))
        df["freight_proxy_chg5"] = pd.Series(chg.reindex(td, method="ffill").to_numpy(), index=idx)
    for c in ("spread12", "crack321", "crack_diesel", "crack_gas"):
        df[f"{c}_z"] = pine_z(df[c])
    from efie.reports.pine_schedule import mark, schedule_string

    df = pd.concat([df, mark(idx, schedule_string(md))], axis=1)
    return df


def build_preview(md: MarketData, bars: int = 500) -> str:
    df = compute(md)
    tail = df.iloc[-bars:]
    labels = {
        "spread12": ("M1–M2 spread", "USD/bbl", True),
        "spread12_z": ("M1–M2 spread z-score (240 bars)", "z", True),
        "crack321": ("3-2-1 crack", "USD/bbl", False),
        "crack_diesel": ("Diesel crack", "USD/bbl", False),
        "crack_gas": ("Gasoline crack", "USD/bbl", False),
        "brent_wti_prev": ("Brent–WTI (previous session)", "USD/bbl", False),
        "freight_proxy_chg5": ("Freight proxy (BWET) 5-session log change", "", True),
    }
    charts = {}
    for k, (title, unit, zero) in labels.items():
        if k in tail:
            s = tail[k].dropna()
            charts[k] = {"title": title, "unit": unit, "zero": zero, "data": [[t.strftime("%m-%d %H:%M"), round(float(v), 4)] for t, v in s.items()]}
    last = df.iloc[-1]
    rows = [
        ("M1–M2 spread", last["spread12"], last["spread12_z"]),
        ("3-2-1 crack", last["crack321"], last["crack321_z"]),
        ("Diesel crack", last["crack_diesel"], last["crack_diesel_z"]),
        ("Gasoline crack", last["crack_gas"], last["crack_gas_z"]),
        ("Brent–WTI (prev.)", last["brent_wti_prev"], np.nan),
        ("Freight proxy 5-sess. (%)", last.get("freight_proxy_chg5", np.nan) * 100, np.nan),
    ]
    f = lambda v: "n/a" if not np.isfinite(v) else f"{v:.2f}"  # noqa: E731
    table = "".join(f"<tr><td>{html.escape(a)}</td><td class='num'>{f(b)}</td><td class='num'>{f(c)}</td></tr>" for a, b, c in rows)
    curve = "backwardation" if last["spread12"] > 0 else "contango"
    page = PAGE.replace("__CSS__", BASE_CSS).replace("__CHART_JS__", CHART_JS).replace("__DATA__", json.dumps(charts))
    from efie.reports.pine_schedule import describe, schedule_string

    sched = schedule_string(md)
    upcoming = describe(sched, md.snapshot)
    page = page.replace("__BAR__", html.escape(str(df.index[-1]))).replace("__TABLE__", table).replace("__CURVE__", curve)
    page = page.replace("__SCHED__", html.escape(sched)).replace("__UPCOMING__", html.escape("; ".join(upcoming) or "none in the calendar window"))
    page = page.replace("__ZHEAD__", f"z ({Z_LEN} × 60)")
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    out = DASHBOARD_DIR / "pine_preview.html"
    out.write_text(page)
    df.tail(50).to_csv(DASHBOARD_DIR / "pine_preview_last50.csv")
    return str(out)


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EFIE Pine Preview</title><style>__CSS__</style></head><body><main>
<header><div><h1>EFIE-R Pine indicator — offline preview</h1><div class="sub">1-hour CL1! chart, last bar __BAR__ (bar open, UTC) · curve: __CURVE__</div></div></header>
<p class="note">These are the series <code>pine/KASPER_EFIE_Research.pine</code> computes. To see the real thing: TradingView → open a <b>new</b> chart tab on NYMEX:CL1! (or MCL1!), 1h →
Pine Editor → New → Indicator → paste the file → Save as “KASPER EFIE Research” → Add to chart. Your existing indicator and layouts are not touched.</p>
<h2>Last-bar table (compare with the indicator's table)</h2><div class="card scroll"><table><thead><tr><th>Quantity</th><th>Level</th><th>__ZHEAD__</th></tr></thead><tbody>__TABLE__</tbody></table></div>
<h2>Release schedule for the indicator</h2><div class="card"><p class="sub">Indicator settings → Release schedule → paste into “Schedule from EFIE”. Upcoming: __UPCOMING__. Regenerate weekly with <code>python -m efie pine-schedule</code>.</p>
<textarea readonly rows="4" style="width:100%;font:12px ui-monospace,monospace;background:var(--page);color:var(--ink);border:1px solid var(--ring);border-radius:6px;padding:8px">__SCHED__</textarea></div>
<h2>Panels (one plot each in the indicator — pick with the “Plot” input)</h2><div class="grid" id="charts"></div>
</main><div class="tt" id="tt"></div><script>const DATA=__DATA__;
__CHART_JS__const host=document.getElementById('charts');Object.keys(DATA).forEach(k=>{const c=document.createElement('div');c.className='card';host.appendChild(c);line(c,DATA[k])});
</script></body></html>
"""
