"""A simple day-ahead price forecast, backtested walk-forward against naive baselines.

Target: the hourly French day-ahead price for delivery day D (Europe/Paris hours; hourly means
of the 15-minute prices after 1 October 2025).

Information set: only what is public before the day-ahead auction closes on D-1 at 12:00 CET:

* prices of D-1 (set by the auction on D-2) and of D-7,
* the TSO's day-ahead load forecast for D (ENTSO-E requires it before the auction),
* the calendar.

Model: for each local hour h, a ridge regression of p(D, h) on
``[1, p(D-1, h), p(D-7, h), mean p(D-1), load forecast(D, h), Mon, Sat, Sun]``, refitted every day
on the previous ``train_days`` days (rolling window). The design and the ridge penalty were fixed
before looking at any backtest result; nothing was tuned on the evaluation period.

Baselines: ``naive_d1`` = p(D-1, h) and ``naive_d7`` = p(D-7, h).

DST change days (23 or 25 local hours) are skipped as targets and as feature days.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from frgrid.areas import LOCAL_TZ

FEATURES = ("const", "p_d1", "p_d7", "mean_d1", "load_fc_gw", "mon", "sat", "sun")


def to_day_hour(series: pd.Series[float]) -> pd.DataFrame:
    """Hourly UTC series -> table of local days (rows) x local hours 0..23 (columns).

    Days that do not have exactly 24 complete local hours (DST changes, gaps) are dropped.
    """
    s = series.dropna()
    idx = pd.DatetimeIndex(s.index).tz_convert(LOCAL_TZ)
    frame = pd.DataFrame(
        {"v": s.to_numpy(), "day": idx.normalize().tz_localize(None), "hour": idx.hour}
    )
    counts = frame.groupby("day")["hour"].nunique()
    sizes = frame.groupby("day").size()
    full = counts[(counts == 24) & (sizes == 24)].index
    table = frame[frame["day"].isin(full)].pivot(index="day", columns="hour", values="v")
    table.index = pd.DatetimeIndex(table.index, name="day")
    return table


@dataclass(frozen=True)
class Backtest:
    """Per-(day, hour) forecasts and the actual price, plus summary metrics."""

    predictions: pd.DataFrame  # columns: actual, model, naive_d1, naive_d7 ; index (day, hour)

    def errors(self) -> pd.DataFrame:
        p = self.predictions
        return p[["model", "naive_d1", "naive_d7"]].sub(p["actual"], axis=0)

    def metrics(self) -> pd.DataFrame:
        e = self.errors()
        return pd.DataFrame(
            {
                "MAE": e.abs().mean(),
                "RMSE": np.sqrt((e**2).mean()),
                "bias": e.mean(),
            }
        ).T

    def metrics_by_year(self) -> pd.DataFrame:
        e = self.errors().abs()
        years = pd.DatetimeIndex(e.index.get_level_values("day")).year
        return e.groupby(years).mean().rename_axis("year")

    def mae_by_month(self) -> pd.DataFrame:
        e = self.errors().abs()
        months = pd.DatetimeIndex(e.index.get_level_values("day")).to_period("M")
        return e.groupby(months).mean().rename_axis("month")

    def diebold_mariano(self, baseline: str = "naive_d1", lags: int = 7) -> tuple[float, float]:
        """DM test on daily mean absolute errors (model vs ``baseline``), Newey-West variance.

        Returns ``(statistic, two-sided p-value)``; a negative statistic favours the model.
        """
        e = self.errors().abs()
        days = e.index.get_level_values("day")
        d = (e["model"] - e[baseline]).groupby(days).mean().to_numpy()
        n = len(d)
        dc = d - d.mean()
        var = float(dc @ dc) / n
        for k in range(1, lags + 1):
            w = 1 - k / (lags + 1)
            var += 2 * w * float(dc[k:] @ dc[:-k]) / n
        stat = float(d.mean() / np.sqrt(var / n))
        from math import erfc, sqrt  # noqa: PLC0415 (only needed here)

        return stat, float(erfc(abs(stat) / sqrt(2)))


def _ridge(x: np.ndarray, y: np.ndarray, penalty: float) -> np.ndarray:
    """Ridge on standardised features (intercept in column 0 is not penalised)."""
    mu = x[:, 1:].mean(axis=0)
    sd = x[:, 1:].std(axis=0)
    sd[sd == 0] = 1.0
    z = np.column_stack([np.ones(len(x)), (x[:, 1:] - mu) / sd])
    reg = penalty * np.eye(z.shape[1])
    reg[0, 0] = 0.0
    beta_z = np.linalg.solve(z.T @ z + reg, z.T @ y)
    beta = np.empty_like(beta_z)
    beta[1:] = beta_z[1:] / sd
    beta[0] = beta_z[0] - float(mu @ beta[1:])
    return beta


def _design(
    prices: pd.DataFrame, load_fc: pd.DataFrame, day: pd.Timestamp, hour: int
) -> np.ndarray | None:
    d1, d7 = day - pd.Timedelta(days=1), day - pd.Timedelta(days=7)
    if d1 not in prices.index or d7 not in prices.index or day not in load_fc.index:
        return None
    p1 = prices.loc[d1].to_numpy(dtype=float)
    p7 = prices.loc[d7].to_numpy(dtype=float)
    lf = load_fc.loc[day].to_numpy(dtype=float)
    dow = day.day_of_week
    return np.array(
        [1.0, p1[hour], p7[hour], p1.mean(), lf[hour] / 1e3, dow == 0, dow == 5, dow == 6],
        dtype=float,
    )


def backtest(
    price_hourly: pd.Series[float],
    load_forecast_hourly: pd.Series[float],
    *,
    train_days: int = 365,
    min_train_days: int = 120,
    penalty: float = 1.0,
    start: pd.Timestamp | None = None,
) -> Backtest:
    """Walk-forward backtest: for each day D, fit on the ``train_days`` days before D only."""
    prices = to_day_hour(price_hourly)
    load_fc = to_day_hour(load_forecast_hourly)
    days = [d for d in prices.index if start is None or d >= start]
    records: list[tuple[pd.Timestamp, int, float, float, float, float]] = []
    for h in range(24):
        # Feature rows for every day that has them, in date order.
        rows = [(d, _design(prices, load_fc, d, h)) for d in prices.index]
        valid = [(d, r) for d, r in rows if r is not None]
        if not valid:
            continue
        hdays = pd.DatetimeIndex([d for d, _ in valid])
        x_all = np.vstack([r for _, r in valid])
        y_all = prices.loc[hdays, h].to_numpy()
        for day in days:
            i = hdays.searchsorted(day)
            if i >= len(hdays) or hdays[i] != day:
                continue  # no features for this target
            lo = hdays.searchsorted(day - pd.Timedelta(days=train_days))
            if i - lo < min_train_days:
                continue
            beta = _ridge(x_all[lo:i], y_all[lo:i], penalty)  # strictly before D
            row = x_all[i]
            records.append(
                (day, h, float(y_all[i]), float(row @ beta), float(row[1]), float(row[2]))
            )
    frame = pd.DataFrame(
        records, columns=["day", "hour", "actual", "model", "naive_d1", "naive_d7"]
    )
    return Backtest(frame.set_index(["day", "hour"]).sort_index())
