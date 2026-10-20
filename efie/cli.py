"""Command line: ``python -m efie <command>`` (run from the ``kasper/`` folder)."""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path


def _md():
    from efie.features.build import load_market_data

    md = load_market_data()
    if md.hourly["CL1"].empty:
        sys.exit("No CL1 hourly data staged. See docs/RUNBOOK.md (stage connector results or import CSV exports).")
    return md


def cmd_status(a):
    from efie.validation.diagnostics import coverage

    md = _md()
    print(f"snapshot: {md.snapshot}")
    for r in coverage(md):
        print(f"  {r['series']:22s} {r['interval']:8s} rows={r['rows']:6d}  {r['first'][:16]} → {r['last'][:16]}")


def cmd_stage(a):
    from efie.ingest.stage import stage

    print(json.dumps(stage(Path(a.file), a.name, json.loads(a.request), a.source), indent=2))


def cmd_import_csv(a):
    from efie.ingest.csv_import import import_csv

    print(json.dumps(import_csv(Path(a.file), a.series, a.interval, a.tz), indent=2))


def cmd_diagnose(a):
    from efie.validation.diagnostics import run_diagnostics

    d = run_diagnostics(_md())
    print(json.dumps({k: d[k] for k in ("eia_weeks", "rolls_daily_vs_hourly_same_date")}, indent=2))
    print("hourly rolls:", d["rolls_hourly"]["by_method"], "daily rolls:", d["rolls_daily"]["by_method"])


def cmd_validate(a):
    from efie.validation.run import run_validation

    res = run_validation(_md())
    for h, r in res["horizons"].items():
        for m in ("tech", "tech_fund"):
            s, g = r["scores"][m], r["gate"][m]
            print(f"{h:13s} {m:9s} n={s['n']:5d} BSS={s['bss']:+.4f} CI=[{s['bss_ci'][0]:+.4f},{s['bss_ci'][1]:+.4f}] cov={s['coverage']:.3f}  "
                  + " ".join(f"{k}:{v['verdict']}" for k, v in g.items()))


def cmd_hypotheses(a):
    from efie.config import load_config
    from efie.paths import EVIDENCE_DIR
    from efie.validation.hypotheses import run_hypotheses

    res = run_hypotheses(_md(), load_config())
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "hypotheses.json").write_text(json.dumps(res, indent=2, default=str))
    for grp in ("sanity", "family"):
        for k, t in res[grp].items():
            extra = f" holm={t['p_holm']:.3f} sig={t['significant_after_holm']}" if "p_holm" in t else ""
            print(f"{k:45s} n={t['n']:5d} rho={t['rho']:+.3f} CI=[{t['ci'][0]:+.3f},{t['ci'][1]:+.3f}]{extra}")


def cmd_backtest(a):
    from efie.backtest.run import run_backtests

    res = run_backtests(_md(), signal_files=[Path(f) for f in a.signals or []])
    for k, t in res["tests"].items():
        print(f"{k:60s} Δ/session={t['mean_diff_usd_per_session']:+7.2f} CI=[{t['ci'][0]:+.2f},{t['ci'][1]:+.2f}] holm={t['p_holm']:.3f} sig={t['significant_after_holm']}")


def cmd_report(a):
    from efie.reports.build import make_report, write_report

    rep = make_report(a.kind, _md(), a.asof)
    j, m = write_report(rep)
    print(m)
    print(j)
    if a.print:
        print(Path(m).read_text())


def cmd_dashboard(a):
    from efie.reports.dashboard import build_dashboard

    print(build_dashboard(_md()))


def cmd_pine_preview(a):
    from efie.reports.pine_preview import build_preview

    print(build_preview(_md()))


def cmd_evidence(a):
    from efie.reports.evidence import write_evidence

    print(write_evidence())


def cmd_run_all(a):
    from efie.backtest.run import run_backtests
    from efie.config import load_config
    from efie.paths import EVIDENCE_DIR
    from efie.reports.build import make_report, write_report
    from efie.reports.dashboard import build_dashboard
    from efie.reports.evidence import write_evidence
    from efie.reports.pine_preview import build_preview
    from efie.validation.diagnostics import run_diagnostics
    from efie.validation.hypotheses import run_hypotheses
    from efie.validation.run import run_validation

    md = _md()
    steps = [
        ("diagnostics", lambda: run_diagnostics(md)),
        ("walk-forward validation", lambda: run_validation(md)),
        ("hypothesis tests", lambda: (EVIDENCE_DIR / "hypotheses.json").write_text(json.dumps(run_hypotheses(md, load_config()), indent=2, default=str))),
        ("overlay backtests", lambda: run_backtests(md, signal_files=[Path(f) for f in a.signals or []])),
        ("hourly report", lambda: print("  ", write_report(make_report("hourly", md))[1])),
        ("daily report", lambda: print("  ", write_report(make_report("daily", md))[1])),
        ("dashboard", lambda: print("  ", build_dashboard(md))),
        ("pine preview", lambda: print("  ", build_preview(md))),
        ("evidence summary", lambda: print("  ", write_evidence())),
    ]
    for name, fn in steps:
        print(f"[efie] {name} …", flush=True)
        fn()
    print("[efie] done")


def main(argv=None):
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    p = argparse.ArgumentParser(prog="python -m efie", description="KASPER V4 Energy Fundamental Intelligence Engine (research only)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="data inventory").set_defaults(fn=cmd_status)
    s = sub.add_parser("stage", help="stage a saved connector result with provenance")
    s.add_argument("file")
    s.add_argument("name")
    s.add_argument("request", help="JSON describing the request (tool, symbol, interval, …)")
    s.add_argument("--source", default="tradingview")
    s.set_defaults(fn=cmd_stage)
    s = sub.add_parser("import-csv", help="import a TradingView chart export or broker OHLCV CSV")
    s.add_argument("file")
    s.add_argument("--series", required=True, help="CL1, CL2, MCL1, RB1, HO1, BRN1, TL1 or BWET")
    s.add_argument("--interval", required=True, choices=["1h", "1D"])
    s.add_argument("--tz", default="UTC", help="time zone of naive timestamps in the file")
    s.set_defaults(fn=cmd_import_csv)
    sub.add_parser("diagnose", help="coverage, roll reconstruction, release alignment").set_defaults(fn=cmd_diagnose)
    sub.add_parser("validate", help="walk-forward validation + gate").set_defaults(fn=cmd_validate)
    sub.add_parser("hypotheses", help="pre-registered event studies").set_defaults(fn=cmd_hypotheses)
    s = sub.add_parser("backtest", help="overlay backtests after costs")
    s.add_argument("--signals", nargs="*", help="your strategy position CSVs (time, position); name containing 'daily' → daily")
    s.set_defaults(fn=cmd_backtest)
    s = sub.add_parser("report", help="hourly or daily report")
    s.add_argument("kind", choices=["hourly", "daily"])
    s.add_argument("--asof", help="replay as of this UTC time, e.g. 2026-10-15T17:00Z")
    s.add_argument("--print", action="store_true", help="print the markdown")
    s.set_defaults(fn=cmd_report)
    sub.add_parser("dashboard", help="build dashboard/index.html").set_defaults(fn=cmd_dashboard)
    sub.add_parser("pine-preview", help="build dashboard/pine_preview.html").set_defaults(fn=cmd_pine_preview)
    sub.add_parser("evidence", help="write docs/evidence/EVIDENCE.md").set_defaults(fn=cmd_evidence)
    s = sub.add_parser("run-all", help="the whole research pipeline")
    s.add_argument("--signals", nargs="*")
    s.set_defaults(fn=cmd_run_all)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
