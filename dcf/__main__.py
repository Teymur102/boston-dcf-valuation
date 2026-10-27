"""Command line entry point.

    python -m dcf run TJX                      # uses cached data in data/ when present
    python -m dcf run TJX --refresh            # re-download everything
    python -m dcf run BSX --peers MDT,ABT,SYK  # any SEC-registered ticker
    python -m dcf run TJX --readme             # also regenerate README.md and docs/DETAILS.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings

from . import config


def _jsonable(o):
    if hasattr(o, "item"):
        return o.item()
    return str(o)


def run(args) -> int:
    warnings.filterwarnings("ignore")
    from . import excel, figures, pipeline
    from .verify import recalc_workbook

    t0 = time.time()
    ticker = args.ticker.upper()
    peers = [p.strip().upper() for p in args.peers.split(",")] if args.peers else \
        config.DEFAULT_PEERS.get(ticker)
    if not peers:
        print("No default peers for this ticker; pass --peers A,B,C", file=sys.stderr)
        return 2
    print(f"[1/5] Loading data for {ticker} (peers: {', '.join(peers)})"
          f"{' - refreshing' if args.refresh else ''}")
    m = pipeline.build(ticker, peers, refresh=args.refresh,
                       terminal_growth=args.terminal_growth)
    res = pipeline.to_json(m)

    out, figs = config.OUTPUT_DIR, config.ROOT / "figures"
    out.mkdir(exist_ok=True)
    figs.mkdir(exist_ok=True)
    xlsx = out / f"{ticker}_dcf.xlsx"
    print("[2/5] Writing Excel workbook with live formulas")
    excel.write_workbook(m, xlsx)

    print("[3/5] Recalculating the workbook independently (pycel) and comparing with Python")
    check = recalc_workbook(xlsx)
    res["workbook_check"] = {
        "excel_price_gordon": check["px_gordon"], "excel_price_exit": check["px_exit"],
        "excel_wacc": check["wacc"], "excel_beta": check["beta"],
        "abs_diff_gordon": abs(check["px_gordon"] - res["implied_price_gordon"]),
        "abs_diff_exit": abs(check["px_exit"] - res["implied_price_exit"]),
    }
    ok = res["workbook_check"]["abs_diff_gordon"] < 0.01 and \
        res["workbook_check"]["abs_diff_exit"] < 0.01
    print(f"      workbook ${check['px_gordon']:.4f} vs Python ${res['implied_price_gordon']:.4f}"
          f" -> {'match' if ok else 'MISMATCH'}")

    print("[4/5] Drawing figures")
    figures.football_field(m, figs / f"{ticker}_football_field.png")
    figures.sensitivity_heatmap(m, figs / f"{ticker}_sensitivity.png")

    (out / f"{ticker}_results.json").write_text(json.dumps(res, indent=2, default=_jsonable))
    print("[5/5] Results")
    if args.readme:
        from .readme import write_details, write_readme
        (config.ROOT / "docs").mkdir(exist_ok=True)
        write_details(res, config.ROOT / "docs" / "DETAILS.md")
        write_readme(res, config.ROOT / "README.md")
        print("      README.md and docs/DETAILS.md regenerated from results")
    print(f"      Share price            ${res['price']:.2f} ({res['valuation_date']})")
    print(f"      DCF (Gordon growth)    ${res['implied_price_gordon']:.2f} "
          f"({res['upside_gordon']:+.1%})")
    print(f"      DCF (exit multiple)    ${res['implied_price_exit']:.2f} "
          f"({res['upside_exit']:+.1%})")
    print(f"      WACC {res['wacc']:.2%} | beta {res['beta']:.2f} | terminal growth "
          f"{res['assumptions']['terminal_growth']:.1%} | exit {res['exit_multiple']:.1f}x")
    print(f"      Done in {time.time() - t0:.1f}s -> {xlsx.relative_to(config.ROOT)}")
    return 0 if ok else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m dcf", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="value a company")
    r.add_argument("ticker")
    r.add_argument("--peers", help="comma-separated peer tickers for trading comps")
    r.add_argument("--refresh", action="store_true", help="re-download all source data")
    r.add_argument("--terminal-growth", type=float, default=config.TERMINAL_GROWTH)
    r.add_argument("--readme", action="store_true", help="regenerate README.md and docs/DETAILS.md")
    a = p.parse_args(argv)
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
