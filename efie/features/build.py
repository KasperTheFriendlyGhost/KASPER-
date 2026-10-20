"""Assemble point-in-time decision frames.

Hourly frame: one row per CL1 hourly bar, indexed by the bar's open time ``t``. The
decision is taken at the bar's close ``tau = t + 1h`` and may use only what was known
at ``tau``. Targets are contract-consistent log returns from ``tau`` to the close of bar
``t+h`` (h = 1, 4); a target is valid only if that span is h hours of trading (the daily
17:00–18:00 ET halt is allowed; weekends and holidays are not).

Daily frame: one row per CME trading date ``D``; the decision is taken at the 17:00 ET
session close of ``D``; the target is the next session's consistent log return.

Feature families (names are prefixed so models can select them):
``tech_*`` price-only; ``ts_*`` term structure; ``crk_*`` crack spreads;
``inv_*`` inventories/refinery (EIA, API); ``frt_*`` freight; ``arb_*`` Brent–WTI;
``rig_*`` rig counts.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from efie.config import load_config
from efie.features.asof import asof_join
from efie.features.inventories import eia_minus_api, release_features, wide_by_release
from efie.ingest.tradingview import daily_close_frame, load_calendar_events, load_ohlcv
from efie.market.calendar import business_day, product_last_trade_date
from efie.market.rolls import (
    consistent_log_returns,
    consistent_price_change,
    roll_calendar,
    roll_flags,
    uncertain_window,
)
from efie.market.sessions import ET, hourly_trading_date, session_close_utc

H = pd.Timedelta(hours=1)


@dataclass(frozen=True)
class MarketData:
    hourly: dict[str, pd.DataFrame]
    daily: dict[str, pd.DataFrame]
    events: pd.DataFrame
    roll_h: pd.DataFrame
    roll_d: pd.DataFrame
    snapshot: pd.Timestamp


def load_market_data() -> MarketData:
    hourly = {s: load_ohlcv(s, "1h") for s in ("CL1", "CL2", "MCL1", "RB1", "HO1", "BWET")}
    daily = {s: daily_close_frame(s) for s in ("CL1", "CL2", "RB1", "HO1", "BRN1", "TL1")}
    events = load_calendar_events()
    roll_h = roll_calendar(hourly["CL1"]["c"], hourly["CL2"]["c"], hourly=True, front_open=hourly["CL1"]["o"])
    roll_d = roll_calendar(daily["CL1"]["c"], daily["CL2"]["c"], hourly=False, front_open=daily["CL1"]["o"], override=roll_h)
    snapshot = max(df.index.max() for df in hourly.values() if len(df)) + H
    return MarketData(hourly, daily, events, roll_h, roll_d, snapshot)


def truncate(md: MarketData, asof: pd.Timestamp) -> MarketData:
    """What was knowable at ``asof``: closed bars, settled sessions, published releases."""
    asof = pd.Timestamp(asof)
    hourly = {k: v[v.index + H <= asof] for k, v in md.hourly.items()}
    daily = {}
    for k, v in md.daily.items():
        closes = pd.DatetimeIndex([session_close_utc(d) for d in v.index])
        daily[k] = v[closes <= asof]
    ev = md.events[md.events["release_ts"] <= asof]
    return replace(md, hourly=hourly, daily=daily, events=ev, snapshot=asof)


# ---------------------------------------------------------------------------- helpers


def zscore(x: pd.Series, n: int) -> pd.Series:
    mu = x.rolling(n, min_periods=n // 2).mean()
    sd = x.rolling(n, min_periods=n // 2).std()
    return (x - mu) / sd


def masked_diff(x: pd.Series, n: int, bad: pd.Series) -> pd.Series:
    """``x - x.shift(n)``, undefined where a contract switch fell inside the span."""
    contaminated = bad.astype(float).rolling(n, min_periods=1).max().astype(bool)
    return (x - x.shift(n)).where(~contaminated)


def product_roll_window(trading_dates: pd.DatetimeIndex) -> np.ndarray:
    """RB/HO front-month switch windows (last business day of month ±; ``LTD-4 … LTD+1``)."""
    bd = business_day()
    td = pd.DatetimeIndex(trading_dates)
    out = np.zeros(len(td), dtype=bool)
    if not len(td):
        return out
    for m in pd.period_range(td.min() - pd.DateOffset(months=1), td.max() + pd.DateOffset(months=2), freq="M"):
        ltd = product_last_trade_date(m.year, m.month)
        out |= (td >= ltd - 4 * bd) & (td <= ltd + bd)
    return out


def _daily_obs(md: MarketData, cfg: dict) -> dict[str, pd.DataFrame]:
    """Daily series as point-in-time observations with ``available_ts``."""
    bd = business_day()
    lagged = set(cfg["point_in_time"]["lag_one_day"])
    out: dict[str, pd.DataFrame] = {}
    for name in ("TL1", "BRN1", "RB1", "HO1", "CL1"):
        d = md.daily.get(name)
        if d is None or d.empty:
            continue
        avail_day = [di + bd if name in lagged else di for di in d.index]
        obs = pd.DataFrame({"date": d.index, "close": d["c"].to_numpy()})
        obs["available_ts"] = [session_close_utc(x) for x in avail_day]
        out[name] = obs
    bw = md.hourly.get("BWET")
    if bw is not None and len(bw):
        # Only completed ETF sessions count: a day's close is known at 16:00 ET (+5 min).
        # A partly traded day is not a "daily close", whenever the data were cut.
        et_date = pd.DatetimeIndex(bw.index.tz_convert(ET).date.astype("datetime64[ns]"))
        last = pd.DataFrame({"c": bw["c"].to_numpy(), "date": et_date}).groupby("date").last()
        avail = pd.DatetimeIndex(
            [pd.Timestamp(d.date()).tz_localize(ET) + pd.Timedelta(hours=16, minutes=5) for d in last.index]
        ).tz_convert("UTC")
        done = avail <= md.snapshot
        out["BWET"] = pd.DataFrame({"date": last.index[done], "close": last["c"].to_numpy()[done], "available_ts": avail[done]})
    return out


def _freight_and_arb(md: MarketData, cfg: dict, decision_ts: pd.DatetimeIndex) -> pd.DataFrame:
    obs = _daily_obs(md, cfg)
    stale = pd.Timedelta(days=cfg["point_in_time"]["max_staleness_days"])
    cols = {}
    if "TL1" in obs:
        o = obs["TL1"].copy()
        lc = np.log(o["close"])
        o["chg5"], o["chg20"], o["z250"] = lc.diff(5), lc.diff(20), zscore(o["close"], 250)
        j = asof_join(decision_ts, o, ["close", "chg5", "chg20", "z250"])
        fresh = (pd.Series(decision_ts, index=decision_ts) - j["known_since"]) <= stale
        cols["frt_td3c_level"] = j["close"].where(fresh)
        cols["frt_td3c_chg5"] = j["chg5"].where(fresh)
        cols["frt_td3c_chg20"] = j["chg20"].where(fresh)
        cols["frt_td3c_z250"] = j["z250"].where(fresh)
        cols["frt_td3c_age_days"] = (pd.Series(decision_ts, index=decision_ts) - j["known_since"]).dt.total_seconds() / 86400
    if "BWET" in obs:
        o = obs["BWET"].copy()
        lc = np.log(o["close"])
        o["chg5"], o["chg20"] = lc.diff(5), lc.diff(20)
        j = asof_join(decision_ts, o, ["chg5", "chg20"])
        fresh = (pd.Series(decision_ts, index=decision_ts) - j["known_since"]) <= stale
        cols["frt_bwet_chg5"] = j["chg5"].where(fresh)
        cols["frt_bwet_chg20"] = j["chg20"].where(fresh)
    if "BRN1" in obs and "CL1" in obs:
        b = obs["BRN1"].set_index("date")
        c = obs["CL1"].set_index("date")
        sp = (b["close"] - c["close"].reindex(b.index)).dropna()
        o = pd.DataFrame({"date": sp.index, "spread": sp.to_numpy(), "available_ts": b.loc[sp.index, "available_ts"].to_numpy()})
        o["chg5"], o["z250"] = o["spread"].diff(5), zscore(o["spread"], 250)
        j = asof_join(decision_ts, o, ["spread", "chg5", "z250"])
        cols["arb_brent_wti"] = j["spread"]
        cols["arb_brent_wti_chg5"] = j["chg5"]
        cols["arb_brent_wti_z250"] = j["z250"]
    return pd.DataFrame(cols, index=decision_ts)


INV_SERIES = {
    "eia_crude": ["surprise_z", "change_z", "seasonal_dev_z", "actual", "consensus"],
    "eia_gasoline": ["surprise_z", "change_z", "seasonal_dev_z", "actual", "consensus"],
    "eia_distillate": ["surprise_z", "change_z", "seasonal_dev_z", "actual", "consensus"],
    "eia_cushing": ["change_z", "seasonal_dev_z", "actual"],
    "eia_runs": ["change_z", "actual"],
    "eia_imports": ["change_z", "actual"],
    "api_crude": ["surprise_z", "change_z", "actual", "consensus"],
    "bh_oil_rigs": ["actual", "previous"],
}


def _inventories(md: MarketData, cfg: dict, decision_ts: pd.DatetimeIndex) -> pd.DataFrame:
    if md.events.empty:
        return pd.DataFrame(index=decision_ts)
    feat = release_features(md.events, cfg["point_in_time"]["release_buffer_minutes"])
    dts = pd.Series(decision_ts, index=decision_ts)
    out = {}
    for series, cols in INV_SERIES.items():
        rel = wide_by_release(feat, series, [c for c in cols if c in feat.columns] + (["previous"] if "previous" in cols else []))
        rel = rel.loc[:, ~rel.columns.duplicated()]
        use = [c for c in cols if c in rel.columns]
        if rel.empty:
            continue
        j = asof_join(decision_ts, rel, use)
        age_h = (dts - j["known_since"]).dt.total_seconds() / 3600
        out[f"inv_{series}_age_h"] = age_h
        for c in use:
            out[f"inv_{series}_{c}"] = j[c]
    m = eia_minus_api(feat)
    if len(m):
        j = asof_join(decision_ts, m, ["eia_minus_api_z"])
        out["inv_eia_minus_api_z"] = j["eia_minus_api_z"]
    df = pd.DataFrame(out, index=decision_ts)
    # Combined crude+gasoline+distillate surprise, scaled by its own past dispersion.
    parts = [f"inv_eia_{s}_surprise_z" for s in ("crude", "gasoline", "distillate")]
    if all(p in df for p in parts):
        df["inv_eia_total_surprise_z"] = df[parts].sum(axis=1, min_count=1) / np.sqrt(3)
    if "inv_bh_oil_rigs_actual" in df:
        df["rig_oil_change"] = df["inv_bh_oil_rigs_actual"] - df["inv_bh_oil_rigs_previous"]
    return df


def _with_fresh_interactions(df: pd.DataFrame, windows: dict[str, float]) -> pd.DataFrame:
    """``x_fresh{w}`` = x where the release is at most ``w`` hours old, else 0."""
    add = {}
    for series in ("eia_crude", "eia_gasoline", "eia_distillate", "eia_cushing", "api_crude"):
        age = df.get(f"inv_{series}_age_h")
        if age is None:
            continue
        for label, hrs in windows.items():
            on = (age <= hrs).astype(float)
            add[f"inv_{series}_is_{label}"] = on
            for c in ("surprise_z", "change_z"):
                col = f"inv_{series}_{c}"
                if col in df:
                    add[f"{col}_{label}"] = df[col].fillna(0.0) * on
    tot = df.get("inv_eia_total_surprise_z")
    if tot is not None and "inv_eia_crude_age_h" in df:
        for label, hrs in windows.items():
            add[f"inv_eia_total_surprise_z_{label}"] = tot.fillna(0.0) * (df["inv_eia_crude_age_h"] <= hrs).astype(float)
    return pd.concat([df, pd.DataFrame(add, index=df.index)], axis=1)


# ---------------------------------------------------------------------------- hourly


def build_hourly(md: MarketData, cfg: dict | None = None) -> pd.DataFrame:
    cfg = cfg or load_config()
    cl1 = md.hourly["CL1"]
    idx = cl1.index
    cl2 = md.hourly["CL2"].reindex(idx)
    tau = pd.DatetimeIndex(idx + H)
    rolls = roll_flags(idx, md.roll_h)
    r = consistent_log_returns(cl1["c"], cl2["c"], rolls)
    td = hourly_trading_date(idx)

    f = pd.DataFrame(index=idx)
    f["tau"] = tau
    f["trading_date"] = td
    f["close"] = cl1["c"]
    f["close_m2"] = cl2["c"]
    f["volume"] = cl1["v"]
    f["r"] = r
    f["dP"] = consistent_price_change(cl1["c"], cl2["c"], rolls)
    f["roll"] = rolls
    f["roll_uncertain"] = uncertain_window(idx, md.roll_h, td).to_numpy()

    # Technical (price-only) — the baseline feature set.
    vol120 = r.rolling(120, min_periods=60).std()
    adj = np.exp(r.fillna(0.0).cumsum())
    f["tech_ret_1"] = r
    f["tech_ret_4"] = r.rolling(4).sum()
    f["tech_ret_24"] = r.rolling(24).sum()
    f["tech_vol_24"] = r.rolling(24, min_periods=12).std()
    f["tech_vol_ratio"] = f["tech_vol_24"] / vol120
    f["tech_ema_gap"] = np.log(adj.ewm(span=20, adjust=False).mean() / adj.ewm(span=50, adjust=False).mean()) / vol120
    hi, lo = adj.rolling(24).max(), adj.rolling(24).min()
    f["tech_range_pos_24"] = ((adj - lo) / (hi - lo)).clip(0, 1) - 0.5
    f["vol_120"] = vol120

    # Term structure.
    spr = cl1["c"] - cl2["c"]
    f["ts_spread12"] = spr
    f["ts_spread12_pct"] = spr / cl1["c"]
    f["ts_spread12_z"] = zscore(spr, 240)
    f["ts_spread12_chg24"] = masked_diff(spr, 24, rolls)

    # Cracks (USD/bbl). RB/HO roll at month end, CL two days before its LTD.
    rb = md.hourly["RB1"]["c"].reindex(idx)
    ho = md.hourly["HO1"]["c"].reindex(idx)
    crack321 = (2 * rb * 42 + ho * 42 - 3 * cl1["c"]) / 3
    diesel = ho * 42 - cl1["c"]
    gas = rb * 42 - cl1["c"]
    switch = pd.Series(rolls.to_numpy() | product_roll_window(td), index=idx)
    for name, s in (("321", crack321), ("diesel", diesel), ("gas", gas)):
        f[f"crk_{name}"] = s
        f[f"crk_{name}_z"] = zscore(s, 480)
        f[f"crk_{name}_chg24"] = masked_diff(s, 24, switch)

    f = pd.concat([f, _freight_and_arb(md, cfg, tau).set_axis(idx), _inventories(md, cfg, tau).set_axis(idx)], axis=1)
    f = _with_fresh_interactions(f, {"fresh": 1.0, "recent": 24.0})

    # Targets.
    for h in (1, 4):
        fwd = sum(r.shift(-k) for k in range(1, h + 1))
        end_close = pd.Series(idx, index=idx).shift(-h) + H
        span = end_close - pd.Series(tau, index=idx)
        f[f"y_{h}"] = fwd
        f[f"y_{h}_valid"] = (span <= pd.Timedelta(hours=h + 1)) & fwd.notna()
        f[f"y_{h}_end"] = end_close
    return f


# ---------------------------------------------------------------------------- daily


def build_daily(md: MarketData, cfg: dict | None = None) -> pd.DataFrame:
    cfg = cfg or load_config()
    cl1 = md.daily["CL1"]
    idx = cl1.index
    cl2 = md.daily["CL2"].reindex(idx)
    tau = pd.DatetimeIndex([session_close_utc(d) for d in idx])
    rolls = roll_flags(idx, md.roll_d)
    r = consistent_log_returns(cl1["c"], cl2["c"], rolls)

    f = pd.DataFrame(index=idx)
    f["tau"] = tau
    f["close"] = cl1["c"]
    f["close_m2"] = cl2["c"]
    f["r"] = r
    f["dP"] = consistent_price_change(cl1["c"], cl2["c"], rolls)
    f["roll"] = rolls
    f["roll_uncertain"] = uncertain_window(idx, md.roll_d).to_numpy()

    vol60 = r.rolling(60, min_periods=30).std()
    adj = np.exp(r.fillna(0.0).cumsum())
    f["tech_ret_1"] = r
    f["tech_ret_5"] = r.rolling(5).sum()
    f["tech_ret_20"] = r.rolling(20).sum()
    f["tech_vol_20"] = r.rolling(20, min_periods=10).std()
    f["tech_vol_ratio"] = f["tech_vol_20"] / vol60
    f["tech_ema_gap"] = np.log(adj.ewm(span=10, adjust=False).mean() / adj.ewm(span=40, adjust=False).mean()) / vol60
    f["vol_60"] = vol60

    spr = cl1["c"] - cl2["c"]
    f["ts_spread12"] = spr
    f["ts_spread12_pct"] = spr / cl1["c"]
    f["ts_spread12_z"] = zscore(spr, 60)
    f["ts_spread12_chg5"] = masked_diff(spr, 5, rolls)

    rb = md.daily["RB1"]["c"].reindex(idx)
    ho = md.daily["HO1"]["c"].reindex(idx)
    crack321 = (2 * rb * 42 + ho * 42 - 3 * cl1["c"]) / 3
    diesel = ho * 42 - cl1["c"]
    gas = rb * 42 - cl1["c"]
    switch = pd.Series(rolls.to_numpy() | product_roll_window(idx), index=idx)
    for name, s in (("321", crack321), ("diesel", diesel), ("gas", gas)):
        f[f"crk_{name}"] = s
        f[f"crk_{name}_z"] = zscore(s, 250)
        f[f"crk_{name}_chg5"] = masked_diff(s, 5, switch)

    f = pd.concat([f, _freight_and_arb(md, cfg, tau).set_axis(idx), _inventories(md, cfg, tau).set_axis(idx)], axis=1)
    # "today" = released since the previous session close (≤ 24h for a weekday release).
    f = _with_fresh_interactions(f, {"today": 24.0})

    # Target: the next session from its 18:00 ET open to its settlement. The daily close
    # is the 14:30 ET settlement, so a decision taken at the 17:00 ET close (which may use,
    # e.g., the 16:30 ET API report) cannot be filled at that settlement; the earliest fill
    # is the next session's open. Open→settle within one daily bar is always one contract.
    f["open"] = cl1["o"]
    f["y_next"] = np.log(cl1["c"] / cl1["o"]).shift(-1)
    f["y_next_valid"] = f["y_next"].notna()
    f["y_next_end"] = pd.Series(tau, index=idx).shift(-1)
    # Gap from this settlement to the next open, earned by the position already held.
    nxt_open = cl1["o"].shift(-1)
    nxt_roll = rolls.shift(-1, fill_value=False)
    f["gap_next"] = (nxt_open - cl1["c"]).where(~nxt_roll, nxt_open - cl2["c"])
    f["intraday_next"] = (cl1["c"] - cl1["o"]).shift(-1)
    return f


FEATURE_PREFIXES = ("tech_", "ts_", "crk_", "frt_", "arb_", "inv_", "rig_")


def feature_columns(df: pd.DataFrame, families: tuple[str, ...]) -> list[str]:
    """Model inputs: standardised/relative columns only (levels in raw units are excluded)."""
    raw_levels = ("_actual", "_consensus", "_previous", "_age_h", "_age_days", "_level")
    cols = []
    for c in df.columns:
        if not c.startswith(families):
            continue
        if c.endswith(raw_levels):
            continue
        if c in ("ts_spread12", "crk_321", "crk_diesel", "crk_gas", "arb_brent_wti", "rig_oil_change"):
            continue
        cols.append(c)
    return cols
