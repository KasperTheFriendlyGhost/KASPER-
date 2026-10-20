"""Roll reconstruction and contract-consistent returns for continuous futures.

TradingView's ``CL1!`` is an unadjusted continuous series: on the roll it switches from
the expiring contract to the next one and the price jumps by roughly the M1–M2 spread.
A return measured across that jump is not a return anyone earned. At a roll bar the new
front contract was the previous bar's *second* month, so the earned return is
``log(F_t / S_{t-1})``.

The connector does not say which contract each print belongs to, so the roll is
reconstructed. For each CL contract the search is confined to a window fixed in advance
by the CME calendar — trading dates ``LTD-4 … LTD+1`` business days, where LTD is the
contract's last trading day — and the bar inside it whose jump best matches a roll
(front price closer to the previous second-month price than to the previous front price)
is taken. When the M1–M2 spread is too narrow to tell the two apart, the vendor's
observed convention (session open two business days before LTD, see
``docs/evidence``) is used; in that case a misplacement costs at most the narrow spread.

This is contract-identity metadata — a trader always knows which contract they hold —
not market information. It is computed once from the full history and passed to the
feature builder as fixed input, so the point-in-time tests compare like with like.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from efie.market.calendar import business_day, cl_last_trade_date
from efie.market.sessions import first_bar_of_session, hourly_trading_date

DEFAULT_OFFSET = -2  # business days relative to LTD (observed TradingView convention 2025–26)
WINDOW = (-4, 1)
NOISE_MULT = 2.0  # the spread must exceed this multiple of recent typical bar moves
MIN_SCORE = 0.6


def _offset_bd(day: pd.Timestamp, ltd: pd.Timestamp) -> int:
    bd = business_day()
    n = len(pd.bdate_range(min(day, ltd), max(day, ltd), freq=bd)) - 1
    return n if day >= ltd else -n


def roll_calendar(
    front: pd.Series,
    second: pd.Series,
    hourly: bool,
    front_open: pd.Series | None = None,
    override: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """One row per contract roll inside the data span: where it happened and how it was found.

    The roll shows most clearly at the session open: the new front month opens next to
    where it closed the evening before as the second month. With ``front_open`` given, the
    test compares the session's opening print with the previous closes of both months
    (overnight gaps are small, so a spread-sized jump stands out); otherwise closes are
    used. ``override`` (a calendar from finer-grained data) fixes the roll trading date for
    any contract it covers.
    """
    f = front.astype(float)
    s = second.reindex(f.index).astype(float)
    now = (front_open.reindex(f.index) if front_open is not None else f).astype(float)
    bd = business_day()
    if hourly:
        tdates = hourly_trading_date(f.index)
        eligible = first_bar_of_session(f.index)
        noise_n = 20
    else:
        tdates = pd.DatetimeIndex(f.index)
        eligible = np.ones(len(f), dtype=bool)
        noise_n = 20
    # Typical size of the same test statistic away from rolls (session-open gaps).
    gap = (now - f.shift(1)).abs().where(eligible)
    noise = gap.dropna().shift(1).rolling(noise_n, min_periods=noise_n // 2).median().reindex(f.index).ffill().to_numpy()
    fixed = {} if override is None else dict(zip(override["contract"], override["roll_trading_date"]))
    span_lo, span_hi = tdates[1], tdates[-1]
    months = pd.period_range(span_lo - pd.DateOffset(months=1), span_hi + pd.DateOffset(months=2), freq="M")
    rows = []
    fv, sv, nv = f.to_numpy(), s.to_numpy(), now.to_numpy()
    for m in months:
        contract = f"{m.year}-{m.month:02d}"
        ltd = cl_last_trade_date(m.year, m.month)
        lo, hi = ltd + WINDOW[0] * bd, ltd + WINDOW[1] * bd
        if hi < span_lo or lo > span_hi:
            continue
        pos = np.where(eligible & (tdates >= lo) & (tdates <= hi))[0]
        pos = pos[pos >= 1]
        if not len(pos):
            continue
        spread = np.abs(fv[pos - 1] - sv[pos - 1])
        scores = (np.abs(nv[pos] - fv[pos - 1]) - np.abs(nv[pos] - sv[pos - 1])) / np.where(spread > 0, spread, np.nan)
        clear = spread >= NOISE_MULT * noise[pos]
        scores = np.where(clear, scores, np.nan)
        if contract in fixed:
            hit = np.where(tdates[pos] == fixed[contract])[0]
            i, how = (int(pos[hit[0]]), "from_hourly") if len(hit) else (None, None)
        else:
            i, how = None, None
        if i is None and np.isfinite(scores).any() and np.nanmax(scores) >= MIN_SCORE:
            i, how = int(pos[int(np.nanargmax(scores))]), "detected"
        if i is None:
            default_day = ltd + DEFAULT_OFFSET * bd
            j = min(int(np.searchsorted(tdates[pos], default_day)), len(pos) - 1)
            i, how = int(pos[j]), "calendar_default"
        rows.append(
            {
                "contract": contract,
                "last_trade_date": ltd,
                "roll_index": f.index[i],
                "roll_trading_date": tdates[i],
                "offset_bd": _offset_bd(tdates[i], ltd),
                "method": how,
                "spread_before": float(fv[i - 1] - sv[i - 1]),
                "score": float(np.nanmax(scores)) if np.isfinite(scores).any() else np.nan,
                "window_start": lo,
                "window_end": hi,
            }
        )
    return pd.DataFrame(rows)


def uncertain_window(index: pd.Index, calendar: pd.DataFrame, trading_dates: pd.DatetimeIndex | None = None) -> pd.Series:
    """Rows inside the search window of a roll that was not pinned down by the data."""
    td = pd.DatetimeIndex(index if trading_dates is None else trading_dates)
    out = np.zeros(len(td), dtype=bool)
    for _, r in calendar[calendar["method"] == "calendar_default"].iterrows():
        out |= (td >= r["window_start"]) & (td <= r["window_end"])
    return pd.Series(out, index=index)


def roll_flags(index: pd.Index, calendar: pd.DataFrame) -> pd.Series:
    flags = pd.Series(False, index=index)
    if len(calendar):
        flags.loc[flags.index.intersection(pd.Index(calendar["roll_index"]))] = True
    return flags


def consistent_log_returns(front: pd.Series, second: pd.Series, rolls: pd.Series) -> pd.Series:
    f = front.astype(float)
    s = second.reindex(f.index).astype(float)
    r_same = np.log(f / f.shift(1))
    r_roll = np.log(f / s.shift(1))
    return r_same.where(~rolls.reindex(f.index, fill_value=False), r_roll)


def consistent_price_change(front: pd.Series, second: pd.Series, rolls: pd.Series) -> pd.Series:
    """Per-bar USD/bbl change earned by holding the front contract (rolled at the roll bar)."""
    f = front.astype(float)
    s = second.reindex(f.index).astype(float)
    d_same = f - f.shift(1)
    d_roll = f - s.shift(1)
    return d_same.where(~rolls.reindex(f.index, fill_value=False), d_roll)
