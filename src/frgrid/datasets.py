"""High-level ENTSO-E datasets for France on a uniform 15-minute UTC grid.

Every dataset is returned with a ``DatetimeIndex`` named ``time_utc`` (tz-aware UTC, interval
start) on a regular 15-minute grid. Series published hourly (e.g. day-ahead prices before
1 October 2025, the CH and GB borders) are repeated onto the 15-minute grid, which is exact for
average power in MW and for a price that holds over the whole hour. The native resolution of the
prices is kept in a ``resolution_min`` column.

Units: power in MW (average over the interval), prices in EUR/MWh.

Queries are split into calendar-quarter windows (boundaries at Europe/Paris midnight) to stay
well below ENTSO-E's one-year limit per request.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import pandas as pd

from frgrid.areas import FRANCE, LOCAL_TZ, NEIGHBOURS
from frgrid.client import EntsoeClient
from frgrid.codes import CONSUMPTION_SUFFIX, psr_label
from frgrid.parse import TimeSeries, expand, parse_document

GRID = pd.Timedelta(minutes=15)
INDEX_NAME = "time_utc"


class BudgetExceededError(RuntimeError):
    """The caller's time budget ran out; cached windows make the next run resume."""


@dataclass
class Budget:
    """Optional wall-clock budget checked between requests."""

    deadline: float | None = None
    clock: Callable[[], float] | None = None

    def check(self) -> None:
        if self.deadline is not None and self.clock is not None and self.clock() > self.deadline:
            msg = "time budget exhausted"
            raise BudgetExceededError(msg)


def windows(
    start: pd.Timestamp, end: pd.Timestamp, months: int = 3
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Split ``[start, end)`` at Europe/Paris calendar-quarter starts."""
    for ts in (start, end):
        if ts.tzinfo is None:
            msg = "start and end must be timezone-aware"
            raise ValueError(msg)
    if end <= start:
        msg = "end must be after start"
        raise ValueError(msg)
    local_start = start.tz_convert(LOCAL_TZ)
    edges = pd.date_range(
        local_start.normalize().replace(day=1), end.tz_convert(LOCAL_TZ), freq=f"{months}MS"
    )
    cuts = sorted({start, end, *(e.tz_convert("UTC") for e in edges if start < e < end)})
    return list(itertools.pairwise(cuts))


def _on_grid(ts: TimeSeries) -> pd.Series[float]:
    return expand(ts.values, ts.resolution, GRID)


def _combine(
    pieces: Iterable[pd.Series[float]], start: pd.Timestamp, end: pd.Timestamp
) -> pd.Series[float]:
    parts = [p for p in pieces if not p.empty]
    if not parts:
        return pd.Series(dtype="float64", index=pd.DatetimeIndex([], tz="UTC", name=INDEX_NAME))
    s = pd.concat(parts).sort_index()
    s = s[~s.index.duplicated(keep="first")]
    s = s[(s.index >= start) & (s.index < end)]
    s.index.name = INDEX_NAME
    return s


def _fetch(
    client: EntsoeClient,
    params: dict[str, str],
    value_tag: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    budget: Budget | None,
) -> list[TimeSeries]:
    out: list[TimeSeries] = []
    for w_start, w_end in windows(start, end):
        if budget is not None:
            budget.check()
        content = client.get(params, w_start, w_end)
        if content is not None:
            out.extend(parse_document(content, value_tag))
    return out


def _frame(
    columns: dict[str, pd.Series[float]], start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    index = pd.date_range(start, end, freq=GRID, inclusive="left", name=INDEX_NAME)
    frame = pd.DataFrame({k: v.reindex(index) for k, v in columns.items()}, index=index)
    frame.columns.name = None
    return frame


def day_ahead_prices(
    client: EntsoeClient, start: pd.Timestamp, end: pd.Timestamp, budget: Budget | None = None
) -> pd.DataFrame:
    """Day-ahead (SDAC) prices for France in EUR/MWh, with the native ``resolution_min``."""
    params = {"documentType": "A44", "in_Domain": FRANCE, "out_Domain": FRANCE}
    series = _fetch(client, params, "price.amount", start, end, budget=budget)
    # Some zones publish several classification sequences; keep the first (position 1) if present.
    series = [
        s
        for s in series
        if s.meta.get("classificationSequence_AttributeInstanceComponent.position", "1") == "1"
    ]
    price = _combine((_on_grid(s) for s in series), start, end)
    res = _combine(
        (
            pd.Series(s.resolution / pd.Timedelta(minutes=1), index=_on_grid(s).index)
            for s in series
        ),
        start,
        end,
    )
    return _frame({"price_eur_mwh": price, "resolution_min": res}, start, end)


def load(
    client: EntsoeClient, start: pd.Timestamp, end: pd.Timestamp, budget: Budget | None = None
) -> pd.DataFrame:
    """Total load, MW: realised (A65/A16) and the TSO's day-ahead forecast (A65/A01)."""
    cols: dict[str, pd.Series[float]] = {}
    for name, process in (("load_actual_mw", "A16"), ("load_forecast_mw", "A01")):
        params = {"documentType": "A65", "processType": process, "outBiddingZone_Domain": FRANCE}
        series = _fetch(client, params, "quantity", start, end, budget=budget)
        cols[name] = _combine((_on_grid(s) for s in series), start, end)
    return _frame(cols, start, end)


def generation(
    client: EntsoeClient, start: pd.Timestamp, end: pd.Timestamp, budget: Budget | None = None
) -> pd.DataFrame:
    """Actual generation per production type (A75/A16), MW, one column per PSR type.

    Series reported against ``outBiddingZone_Domain`` are consumption (e.g. pumping of pumped
    storage) and get a ``" (consumption)"`` suffix; they are not part of generation.
    """
    params = {"documentType": "A75", "processType": "A16", "in_Domain": FRANCE}
    series = _fetch(client, params, "quantity", start, end, budget=budget)
    groups: dict[str, list[pd.Series[float]]] = {}
    for s in series:
        label = psr_label(s.meta.get("psrType", "unknown"))
        if "outBiddingZone_Domain.mRID" in s.meta and "inBiddingZone_Domain.mRID" not in s.meta:
            label += CONSUMPTION_SUFFIX
        groups.setdefault(label, []).append(_on_grid(s))
    cols = {k: _combine(v, start, end) for k, v in sorted(groups.items())}
    return _frame(cols, start, end)


def physical_flows(
    client: EntsoeClient, start: pd.Timestamp, end: pd.Timestamp, budget: Budget | None = None
) -> pd.DataFrame:
    """Cross-border physical flows (A11), MW, per border: ``import_XX`` and ``export_XX``.

    In ENTSO-E documents ``in_Domain`` is the area the energy flows *into* and ``out_Domain``
    the area it flows *out of*. Hence import into France = ``in_Domain=FR, out_Domain=XX`` and
    export from France = ``in_Domain=XX, out_Domain=FR``. Both are non-negative.
    """
    cols: dict[str, pd.Series[float]] = {}
    for code, eic in NEIGHBOURS.items():
        for direction, into, out_of in (("import", FRANCE, eic), ("export", eic, FRANCE)):
            params = {"documentType": "A11", "in_Domain": into, "out_Domain": out_of}
            series = _fetch(client, params, "quantity", start, end, budget=budget)
            cols[f"{direction}_{code}"] = _combine((_on_grid(s) for s in series), start, end)
    return _frame(cols, start, end)


DATASETS: dict[
    str, Callable[[EntsoeClient, pd.Timestamp, pd.Timestamp, Budget | None], pd.DataFrame]
] = {
    "prices": day_ahead_prices,
    "load": load,
    "generation": generation,
    "flows": physical_flows,
}
