"""Command line entry point: ``frgrid fetch``.

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
            path = store.save(name, frame)
            filled = frame.notna().mean().mean()
            print(
                f"{name}: {len(frame):,} rows x {frame.shape[1]} cols, {filled:.1%} filled, "
                f"{time.monotonic() - t0:.0f} s -> {path.name}"
            )
        print(f"HTTP requests made: {client.requests_made}")
    return 0


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
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
