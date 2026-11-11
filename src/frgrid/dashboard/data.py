"""Data layer of the dashboard, independent of any UI framework.

* :func:`load_bundle` reads the datasets saved locally by ``frgrid fetch`` (or by
  :func:`refresh`), together with when they were fetched.
* :func:`refresh` downloads through the existing :class:`~frgrid.client.EntsoeClient`, whose
  cache serves settled windows locally, and marks the result as fetched in this session.
* The remaining functions turn the 15-minute frames into the *aggregated* tables the dashboard
  shows (monthly means, average profiles, backtest summaries). No raw time series are displayed.

Error messages raised here never contain the API token or local file paths.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date

import numpy as np
import pandas as pd

from frgrid import analytics as an
from frgrid import store
from frgrid.areas import LOCAL_TZ, NEIGHBOURS
from frgrid.client import EntsoeClient, EntsoeError
from frgrid.datasets import DATASETS, Budget, BudgetExceededError
from frgrid.forecast import Backtest, backtest
from frgrid.settings import MissingTokenError, load_token

NAMES = ("prices", "load", "generation", "flows")


class DataError(RuntimeError):
    """A user-facing data problem (missing token, ENTSO-E error, time budget reached)."""


@dataclass(frozen=True)
class Bundle:
    """The datasets available to the dashboard and how fresh they are."""

    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    fetched_at: dict[str, pd.Timestamp] = field(default_factory=dict)  # UTC, per dataset
    fetched_in_session: bool = False

    def get(self, name: str) -> pd.DataFrame | None:
        return self.frames.get(name)

    @property
    def available(self) -> list[str]:
        return [n for n in NAMES if n in self.frames]

    @property
    def missing(self) -> list[str]:
        return [n for n in NAMES if n not in self.frames]

    @property
    def is_empty(self) -> bool:
        return not self.frames

    @property
    def as_of(self) -> pd.Timestamp | None:
        """The *oldest* fetch time among the loaded datasets (conservative freshness)."""
        return min(self.fetched_at.values()) if self.fetched_at else None

    def coverage(self) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        """First and last interval start covered by any dataset, in Europe/Paris time."""
        starts, ends = [], []
        for frame in self.frames.values():
            valid = frame.dropna(how="all")
            if not valid.empty:
                idx = pd.DatetimeIndex(valid.index).tz_convert(LOCAL_TZ)
                starts.append(idx.min())
                ends.append(idx.max())
        if not starts:
            return None
        return min(starts), max(ends)


def load_bundle() -> Bundle:
    """Whatever is stored locally; never raises for missing datasets (see ``Bundle.missing``)."""
    frames: dict[str, pd.DataFrame] = {}
    fetched: dict[str, pd.Timestamp] = {}
    for name in NAMES:
        if not store.exists(name):
            continue
        frames[name] = store.load(name)
        meta = store.read_meta(name)
        if meta is not None:
            fetched[name] = meta.fetched_at
    return Bundle(frames=frames, fetched_at=fetched)


def local_day(d: date) -> pd.Timestamp:
    return pd.Timestamp(d).tz_localize(LOCAL_TZ).tz_convert("UTC")


def refresh(
    start: date,
    end: date,
    *,
    max_minutes: float = 3.0,
    client_factory: Callable[[], EntsoeClient] | None = None,
    names: tuple[str, ...] = NAMES,
) -> Bundle:
    """Download ``[start, end)`` (Europe/Paris days) through the client and save it locally.

    Settled windows come from the local cache; only recent ones hit the API. Returns a bundle
    flagged ``fetched_in_session=True``. Raises :class:`DataError` with a safe message.
    """
    s, e = local_day(start), local_day(end)
    if e <= s:
        msg = "The end date must be after the start date."
        raise DataError(msg)
    if client_factory is None:
        try:
            token = load_token()
        except MissingTokenError:
            msg = "No ENTSO-E token configured: add ENTSOE_API_TOKEN to the .env file."
            raise DataError(msg) from None

        def client_factory() -> EntsoeClient:
            return EntsoeClient(token, cache_dir=store.cache_dir())

    budget = Budget(deadline=time.monotonic() + max_minutes * 60, clock=time.monotonic)
    fetched_at = pd.Timestamp.now(tz="UTC")
    with client_factory() as client:
        for name in names:
            try:
                frame = DATASETS[name](client, s, e, budget)
            except BudgetExceededError:
                msg = (
                    f"Time budget reached while fetching '{name}'. Run the update again: "
                    "finished windows are cached, so it resumes."
                )
                raise DataError(msg) from None
            except EntsoeError as exc:
                raise DataError(f"ENTSO-E error while fetching '{name}': {exc}") from None
            store.save(name, frame, start=s, end=e, fetched_at=fetched_at)
    return replace(load_bundle(), fetched_in_session=True)


# ---- aggregated tables -------------------------------------------------------------------------


def _monthly(frame: pd.DataFrame | pd.Series[float]) -> pd.DataFrame:
    out = frame.tz_convert(LOCAL_TZ).resample("MS").mean()
    df = out.to_frame() if isinstance(out, pd.Series) else out
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).rename("month")
    return df


def clip_months(table: pd.DataFrame, first: pd.Timestamp, last: pd.Timestamp) -> pd.DataFrame:
    """Keep the monthly rows between ``first`` and ``last`` (inclusive, naive month starts)."""
    idx = pd.DatetimeIndex(table.index)
    return table[(idx >= first) & (idx <= last)]


def clip_period(frame: pd.DataFrame, first: pd.Timestamp, last: pd.Timestamp) -> pd.DataFrame:
    """Rows whose Europe/Paris month lies between ``first`` and ``last`` (inclusive)."""
    months = pd.DatetimeIndex(frame.index).tz_convert(LOCAL_TZ).tz_localize(None).to_period("M")
    keep = (months >= first.to_period("M")) & (months <= last.to_period("M"))
    return frame[keep]


def price_profile(prices: pd.DataFrame) -> pd.DataFrame:
    """Mean price (EUR/MWh) by Europe/Paris hour (rows) and season (columns)."""
    return an.daily_profile(an.hourly(prices)["price_eur_mwh"], by="season")


def monthly_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Monthly mean, 10th and 90th percentile of hourly prices, and share of negative hours."""
    p = an.hourly(prices)["price_eur_mwh"].tz_convert(LOCAL_TZ)
    grouped = p.resample("MS")
    out = pd.DataFrame(
        {
            "mean": grouped.mean(),
            "p10": grouped.quantile(0.1),
            "p90": grouped.quantile(0.9),
            "negative_share": (p < 0).astype(float).where(p.notna()).resample("MS").mean(),
        }
    )
    out.index = pd.DatetimeIndex(out.index).tz_localize(None).rename("month")
    return out


def run_backtest(prices: pd.DataFrame, load: pd.DataFrame) -> Backtest:
    return backtest(an.hourly(prices)["price_eur_mwh"], an.hourly(load)["load_forecast_mw"])


def backtest_monthly(bt: Backtest) -> pd.DataFrame:
    """Per delivery month: mean actual and forecast price, and MAE of model and baselines."""
    p = bt.predictions
    months = pd.DatetimeIndex(p.index.get_level_values("day")).to_period("M")
    err = bt.errors().abs()
    out = pd.DataFrame(
        {
            "actual_mean": p["actual"].groupby(months).mean(),
            "model_mean": p["model"].groupby(months).mean(),
            "mae_model": err["model"].groupby(months).mean(),
            "mae_naive_d1": err["naive_d1"].groupby(months).mean(),
            "mae_naive_d7": err["naive_d7"].groupby(months).mean(),
        }
    )
    out.index = pd.PeriodIndex(out.index).to_timestamp().rename("month")
    return out


def backtest_summary(bt: Backtest, first: pd.Timestamp, last: pd.Timestamp) -> pd.DataFrame:
    """MAE / RMSE / bias of model and baselines over the selected months."""
    days = pd.DatetimeIndex(bt.predictions.index.get_level_values("day"))
    keep = (days >= first) & (days < last + pd.offsets.MonthBegin(1))
    sub = Backtest(bt.predictions[keep])
    if sub.predictions.empty:
        return pd.DataFrame()
    return sub.metrics()


def load_monthly(load: pd.DataFrame) -> pd.DataFrame:
    """Monthly mean actual and day-ahead forecast load (GW) and forecast MAE (GW)."""
    h = an.hourly(load)
    err = (h["load_forecast_mw"] - h["load_actual_mw"]).abs()
    df = _monthly(
        pd.DataFrame(
            {
                "actual_gw": h["load_actual_mw"] / 1e3,
                "forecast_gw": h["load_forecast_mw"] / 1e3,
                "forecast_mae_gw": err / 1e3,
            }
        )
    )
    return df


def residual_monthly(load: pd.DataFrame, generation: pd.DataFrame) -> pd.DataFrame:
    """Monthly mean load, wind + solar and residual load, GW."""
    return _monthly(
        an.hourly(
            pd.DataFrame(
                {
                    "load_gw": load["load_actual_mw"] / 1e3,
                    "wind_solar_gw": an.variable_renewables(generation) / 1e3,
                    "residual_gw": an.residual_load(load, generation) / 1e3,
                }
            )
        )
    )


def generation_monthly(generation: pd.DataFrame) -> pd.DataFrame:
    out = an.grouped_generation(generation)
    out.index = pd.DatetimeIndex(out.index).tz_localize(None).rename("month")
    return out


def renewables_co2_monthly(generation: pd.DataFrame) -> pd.DataFrame:
    h = an.hourly(generation)
    return _monthly(
        pd.DataFrame(
            {
                "renewable_share_pct": an.renewable_share(h) * 100,
                "co2_g_per_kwh": an.co2_intensity(h),
            }
        )
    )


def net_position_monthly(flows: pd.DataFrame) -> pd.DataFrame:
    """Monthly mean net *exports* per border, GW (positive = France exports)."""
    net = -an.net_imports(an.hourly(flows)).drop(columns="total") / 1e3
    return _monthly(net)


def border_flows(flows: pd.DataFrame) -> pd.DataFrame:
    """Mean import into and export from France per border over the frame, GW (both >= 0)."""
    h = an.hourly(flows)
    rows = {
        code: {
            "import_gw": float(h[f"import_{code}"].mean()) / 1e3,
            "export_gw": float(h[f"export_{code}"].mean()) / 1e3,
        }
        for code in NEIGHBOURS
        if f"import_{code}" in h and f"export_{code}" in h
    }
    out = pd.DataFrame.from_dict(rows, orient="index")
    out["net_export_gw"] = out["export_gw"] - out["import_gw"]
    out.index.name = "border"
    return out.sort_values("net_export_gw", ascending=False)


def month_options(bundle: Bundle) -> list[pd.Timestamp]:
    """Month starts (naive, Europe/Paris) covered by the bundle, for the period selector."""
    cov = bundle.coverage()
    if cov is None:
        return []
    first, last = cov
    return list(
        pd.date_range(
            first.tz_localize(None).to_period("M").to_timestamp(),
            last.tz_localize(None).to_period("M").to_timestamp(),
            freq="MS",
        )
    )


def format_as_of(ts: pd.Timestamp | None) -> str:
    if ts is None or pd.isna(ts):
        return "unknown"
    return f"{ts.tz_convert(LOCAL_TZ):%Y-%m-%d %H:%M} (Europe/Paris)"


def is_finite_frame(frame: pd.DataFrame) -> bool:
    return bool(np.isfinite(frame.select_dtypes("number").to_numpy()).any())


def store_signature() -> str:
    """Changes whenever a stored dataset or its metadata changes (cache key for the UI)."""
    parts = []
    for name in NAMES:
        for path in (store.path_for(name), store.meta_path_for(name)):
            if path.is_file():
                st = path.stat()
                parts.append(f"{path.name}:{st.st_mtime_ns}:{st.st_size}")
    return "|".join(parts)
