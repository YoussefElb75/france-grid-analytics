"""Command line entry points: ``frgrid fetch``, ``frgrid report`` and ``frgrid dashboard``.

Dates are calendar days in Europe/Paris; ``--end`` is exclusive. Downloads are cached window by
window, so a run stopped by ``--max-minutes`` resumes where it left off.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

import pandas as pd

from frgrid import store
from frgrid.areas import LOCAL_TZ
from frgrid.client import EntsoeClient, EntsoeError
from frgrid.datasets import DATASETS, Budget, BudgetExceededError
from frgrid.settings import MissingTokenError, load_token


def _local_day(text: str) -> pd.Timestamp:
    return pd.Timestamp(text).tz_localize(LOCAL_TZ).tz_convert("UTC")


def cmd_fetch(args: argparse.Namespace) -> int:
    start, end = _local_day(args.start), _local_day(args.end)
    names = list(DATASETS) if args.datasets == ["all"] else args.datasets
    budget = Budget(deadline=time.monotonic() + args.max_minutes * 60, clock=time.monotonic)
    try:
        token = load_token()
    except MissingTokenError as exc:
        print(exc, file=sys.stderr)
        return 2
    with EntsoeClient(token, cache_dir=store.cache_dir()) as client:
        for name in names:
            t0 = time.monotonic()
            try:
                frame = DATASETS[name](client, start, end, budget)
            except BudgetExceededError:
                print(f"{name}: time budget reached; run the same command again to resume.")
                return 3
            except EntsoeError as exc:
                print(f"{name}: {exc}", file=sys.stderr)
                return 1
            path = store.save(name, frame, start=start, end=end)
            filled = frame.notna().mean().mean()
            print(
                f"{name}: {len(frame):,} rows x {frame.shape[1]} cols, {filled:.1%} filled, "
                f"{time.monotonic() - t0:.0f} s -> {path.name}"
            )
        print(f"HTTP requests made: {client.requests_made}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from pathlib import Path  # noqa: PLC0415

    from frgrid import charts, europe_report  # noqa: PLC0415 (matplotlib only needed here)

    out = Path(args.out)
    if all(store.exists(n) for n in ("eu_prices", "flows", "eu_solar")):
        eu_inputs = europe_report.EuropeInputs(
            prices=store.load("eu_prices"),
            flows=store.load("flows"),
            solar=store.load("eu_solar"),
            capacity=store.load("eu_capacity") if store.exists("eu_capacity") else None,
        )
        eu_paths, eu_results = europe_report.build(eu_inputs, out)
        for path in eu_paths:
            print(f"wrote {path}")
        eu_results_path = out.parent / "europe_results.md"
        eu_results_path.write_text(eu_results + chr(10), encoding="utf-8")
        print(f"wrote {eu_results_path}")
    elif args.europe_only:
        print("European datasets missing: run `frgrid fetch` first.", file=sys.stderr)
        return 2
    if args.europe_only:
        return 0

    try:
        flows = store.load("flows")
    except FileNotFoundError:
        flows = None
    inputs = charts.Inputs(
        prices=store.load("prices"),
        load=store.load("load"),
        generation=store.load("generation"),
        flows=flows,
    )
    paths, results = charts.build(inputs, Path(args.out))
    for path in paths:
        print(f"wrote {path}")
    results_path = Path(args.out).parent / "results.md"
    results_path.write_text(results + chr(10), encoding="utf-8")
    print(f"wrote {results_path}")
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    import subprocess  # noqa: PLC0415

    from frgrid.settings import project_root  # noqa: PLC0415

    root = project_root()
    app = root / "app" / "streamlit_app.py"
    if not app.is_file():
        print(
            "app/streamlit_app.py not found; run from a clone of the repository.", file=sys.stderr
        )
        return 2
    cmd = [sys.executable, "-m", "streamlit", "run", str(app), "--server.port", str(args.port)]
    return subprocess.call(cmd, cwd=root)  # noqa: S603 (fixed argument list, no shell)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="frgrid", description=__doc__.splitlines()[0])
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("fetch", help="download datasets into data/processed (Parquet)")
    f.add_argument("--start", required=True, help="first day, Europe/Paris (YYYY-MM-DD)")
    f.add_argument("--end", required=True, help="day after the last day, Europe/Paris")
    f.add_argument("--datasets", nargs="+", default=["all"], choices=["all", *DATASETS])
    f.add_argument("--max-minutes", type=float, default=9.0, help="stop cleanly after this long")
    f.set_defaults(func=cmd_fetch)
    r = sub.add_parser("report", help="build README charts and result tables from local data")
    r.add_argument("--out", default="docs/img", help="folder for the PNG charts")
    r.add_argument(
        "--europe-only", action="store_true", help="only the European charts (skips the backtest)"
    )
    r.set_defaults(func=cmd_report)
    d = sub.add_parser("dashboard", help="start the local Streamlit dashboard")
    d.add_argument("--port", type=int, default=8501)
    d.set_defaults(func=cmd_dashboard)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
