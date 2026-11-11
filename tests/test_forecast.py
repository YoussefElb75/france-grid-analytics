from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from frgrid.forecast import backtest, to_day_hour


def hourly_utc(start: str, days: int) -> pd.DatetimeIndex:
    s = pd.Timestamp(start, tz="Europe/Paris").tz_convert("UTC")
    e = (pd.Timestamp(start, tz="Europe/Paris") + pd.DateOffset(days=days)).tz_convert("UTC")
    return pd.date_range(s, e, freq="1h", inclusive="left", tz="UTC")


def synthetic(days: int = 400, seed: int = 0) -> tuple[pd.Series[float], pd.Series[float]]:
    """Price driven by the load forecast plus noise: the naive baselines should lose."""
    idx = hourly_utc("2024-01-01", days)
    rng = np.random.default_rng(seed)
    local = idx.tz_convert("Europe/Paris")
    load = 50_000 + 10_000 * np.sin(2 * np.pi * local.hour / 24) + rng.normal(0, 4_000, len(idx))
    price = 20 + 0.002 * load + rng.normal(0, 2, len(idx))
    return pd.Series(price, index=idx), pd.Series(load, index=idx)


def test_to_day_hour_drops_dst_days() -> None:
    idx = hourly_utc("2025-03-28", 5)  # includes 30 March 2025 (23 local hours)
    table = to_day_hour(pd.Series(1.0, index=idx))
    assert pd.Timestamp("2025-03-30") not in table.index
    assert table.shape[1] == 24
    assert len(table) == 4


def test_model_beats_naive_on_load_driven_prices() -> None:
    price, load = synthetic()
    bt = backtest(price, load, min_train_days=60)
    mae = bt.metrics().loc["MAE"].astype(float).to_dict()
    assert mae["model"] < 0.7 * mae["naive_d1"]
    assert mae["model"] < 0.7 * mae["naive_d7"]
    stat, pvalue = bt.diebold_mariano()
    assert stat < 0
    assert pvalue < 0.01


def test_naive_baselines_are_the_lagged_prices() -> None:
    price, load = synthetic(days=200)
    bt = backtest(price, load, min_train_days=60)
    table = to_day_hour(price)
    day, hour = bt.predictions.index[0]
    row = bt.predictions.loc[(day, hour)].astype(float).to_dict()
    assert row["naive_d1"] == pytest.approx(table.at[day - pd.Timedelta(days=1), hour])
    assert row["naive_d7"] == pytest.approx(table.at[day - pd.Timedelta(days=7), hour])
    assert row["actual"] == pytest.approx(table.at[day, hour])


def test_no_look_ahead() -> None:
    """Changing data from a cut-off day onwards must not change any earlier forecast."""
    price, load = synthetic(days=260)
    cut = pd.Timestamp("2024-08-01", tz="Europe/Paris").tz_convert("UTC")
    shocked = price.copy()
    shocked[shocked.index >= cut] += 500.0
    base = backtest(price, load, min_train_days=60).predictions
    alt = backtest(shocked, load, min_train_days=60).predictions
    before = base.index.get_level_values("day") < pd.Timestamp("2024-08-01")
    pd.testing.assert_frame_equal(base[before], alt[before])


def test_metric_tables_have_expected_shape() -> None:
    price, load = synthetic(days=200)
    bt = backtest(price, load, min_train_days=60)
    assert list(bt.metrics().index) == ["MAE", "RMSE", "bias"]
    assert list(bt.metrics_by_year().columns) == ["model", "naive_d1", "naive_d7"]
    assert len(bt.mae_by_month()) >= 4
