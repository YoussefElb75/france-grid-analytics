"""European analytics on small synthetic frames with hand-checkable answers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from frgrid import europe as eu
from frgrid.areas import PRICE_ZONES


def grid(periods: int, start: str = "2025-06-01T22:00Z") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=periods, freq="15min", tz="UTC", name="time_utc")


def prices_frame(values: dict[str, list[float]], start: str = "2025-06-01T22:00Z") -> pd.DataFrame:
    n = len(next(iter(values.values())))
    idx = grid(n, start)
    frame = pd.DataFrame(values, index=idx)
    for z in values:
        frame[f"res_{z}"] = 15.0
    return frame


def test_spreads_are_neighbour_minus_france_in_zone_order() -> None:
    p = prices_frame({"ES": [50.0, 70.0], "FR": [60.0, 60.0], "DE_LU": [60.0, 61.0]})
    s = eu.spreads(p)
    assert list(s.columns) == ["DE_LU", "ES"]  # PRICE_ZONES order, FR excluded
    assert s["ES"].tolist() == [-10.0, 10.0]
    assert s["DE_LU"].tolist() == [0.0, 1.0]


def test_convergence_is_equality_to_the_cent_and_ignores_missing() -> None:
    p = prices_frame({"FR": [60.0, 60.0, 60.0, 60.0], "BE": [60.0, 60.004, 60.01, np.nan]})
    c = eu.converged(p)["BE"]
    assert c.iloc[:3].tolist() == [1.0, 1.0, 0.0]
    assert np.isnan(c.iloc[3])
    summary = eu.convergence_summary(p).loc["BE"]
    assert summary["converged"] == pytest.approx(2 / 3)
    assert summary["fr_cheaper"] == pytest.approx(1 / 3)
    assert summary["quarter_hours"] == 3
    assert summary["within_1_eur"] == 1.0


def test_all_zones_converged_needs_every_zone() -> None:
    p = prices_frame({"FR": [1.0, 1.0, 1.0], "BE": [1.0, 1.0, np.nan], "NL": [1.0, 2.0, 1.0]})
    assert eu.all_converged(p).tolist()[:2] == [1.0, 0.0]
    assert np.isnan(eu.all_converged(p).iloc[2])


def test_profiles_use_paris_local_hours_and_months() -> None:
    # 2025-06-01T22:00Z is 00:00 on 2 June in Paris (UTC+2).
    p = prices_frame({"FR": [0.0] * 8, "ES": [4.0] * 4 + [8.0] * 4})
    by_hour = eu.spread_by_hour(eu.spreads(p))
    assert by_hour.loc[0, "ES"] == 4.0
    assert by_hour.loc[1, "ES"] == 8.0
    by_month = eu.spread_by_month(eu.spreads(p))
    assert list(by_month.index) == [pd.Timestamp("2025-06-01")]
    assert by_month.loc["2025-06-01", "ES"] == 6.0


def test_month_boundary_is_local() -> None:
    # 2025-06-30T22:00Z is already July in Paris.
    p = prices_frame({"FR": [10.0, 20.0]}, start="2025-06-30T21:45Z")
    m = eu.monthly_mean_prices(p)
    assert m.loc["2025-06-01", "FR"] == 10.0
    assert m.loc["2025-07-01", "FR"] == 20.0


def test_spread_distribution_percentiles() -> None:
    values = list(np.arange(101, dtype=float))
    p = prices_frame({"FR": [0.0] * 101, "BE": values})
    d = eu.spread_distribution(eu.spreads(p)).loc["BE"]
    assert d["median"] == 50.0
    assert d["p05"] == 5.0
    assert d["p95"] == 95.0
    assert d["mean_abs"] == 50.0


def flows_frame(
    index: pd.DatetimeIndex, export_es: list[float], import_es: list[float]
) -> pd.DataFrame:
    return pd.DataFrame({"export_ES": export_es, "import_ES": import_es}, index=index)


def test_flow_direction_with_and_against_the_spread() -> None:
    # ES dearer, FR exports -> with; ES dearer, FR imports -> against; ES cheaper, FR imports ->
    # with; tiny flow -> none; equal prices -> not counted.
    p = prices_frame({"FR": [50.0, 50.0, 50.0, 50.0, 50.0], "ES": [60.0, 60.0, 40.0, 60.0, 50.0]})
    f = flows_frame(
        pd.DatetimeIndex(p.index), [1000.0, 0.0, 0.0, 30.0, 500.0], [0.0, 800.0, 900.0, 0.0, 0.0]
    )
    d = eu.flow_direction(p, f)["ES"]
    assert d.iloc[:4].tolist() == [1.0, -1.0, 1.0, 0.0]
    assert np.isnan(d.iloc[4])
    summary = eu.flow_vs_spread(p, f).loc["ES"]
    assert summary["with_spread"] == 0.5
    assert summary["against_spread"] == 0.25
    assert summary["no_flow"] == 0.25
    assert summary["decoupled_quarter_hours"] == 4
    assert summary["mean_abs_spread_against"] == 10.0
    assert summary["mean_abs_flow_against_mw"] == 800.0


def test_against_by_spread_size_bins() -> None:
    p = prices_frame({"FR": [50.0] * 3, "ES": [50.5, 60.0, 110.0]})
    f = flows_frame(pd.DatetimeIndex(p.index), [0.0, 0.0, 900.0], [500.0, 500.0, 0.0])
    t = eu.against_by_spread_size(p, f)
    assert t.loc["0-1", "ES"] == 1.0
    assert t.loc["5-20", "ES"] == 1.0
    assert t.loc[">50", "ES"] == 0.0
    assert t["ES"].isna().tolist() == [False, True, False, True, False]


def test_net_exports_map_price_zones_to_v1_border_columns() -> None:
    idx = grid(1)
    flows = pd.DataFrame(
        {"export_DE": [700.0], "import_DE": [200.0], "export_IT": [0.0], "import_IT": [300.0]},
        index=idx,
    )
    net = eu.net_exports(flows)
    assert net.loc[idx[0], "DE_LU"] == 500.0
    assert net.loc[idx[0], "IT_NORTH"] == -300.0
    assert "NL" not in net


def test_negative_prices_by_year_count_equivalent_hours() -> None:
    p = prices_frame({"FR": [-1.0] * 4 + [0.0] * 4, "ES": [-5.0] * 8})
    years = eu.negative_by_year(p)
    assert years.loc[2025, "FR"] == 1.0  # four negative quarter-hours = one hour
    assert years.loc[2025, "ES"] == 2.0
    assert eu.negative(p)["FR"].iloc[4] == 0.0  # zero is not negative


def solar_day() -> tuple[pd.DataFrame, pd.DataFrame]:
    """One local day: solar bell from 06:00 to 18:00, prices negative 11:00-15:00 in ES only."""
    idx = grid(96)
    hour = pd.DatetimeIndex(idx).tz_convert("Europe/Paris").hour.to_numpy()
    bell = np.clip(np.sin(np.pi * (hour - 6) / 12), 0, None)
    solar = pd.DataFrame({"FR": 10_000 * bell, "ES": 20_000 * bell}, index=idx)
    es = np.where((hour >= 11) & (hour < 15), -2.0, 40.0)
    return prices_frame({"FR": [30.0] * 96, "ES": list(es)}), solar


def test_relative_solar_is_scaled_to_the_yearly_peak() -> None:
    _, solar = solar_day()
    rel = eu.relative_solar(solar)
    assert rel.max().max() <= 1.0
    assert rel["FR"].max() == pytest.approx(1.0)
    pd.testing.assert_series_equal(rel["FR"], rel["ES"], check_names=False)
    prof = eu.solar_profile(solar)
    assert prof.loc[0, "ES"] == 0.0
    assert prof.loc[12, "ES"] == pytest.approx(1.0)


def test_negative_prices_line_up_with_solar() -> None:
    prices, solar = solar_day()
    s = eu.negative_solar_summary(prices, solar)
    assert s.loc["ES", "negative_share"] == pytest.approx(16 / 96)
    assert s.loc["ES", "hours_per_year"] == pytest.approx(4 * 365.25)
    assert s.loc["ES", "in_daylight"] == 1.0
    assert s.loc["ES", "solar_above_half"] == 1.0
    assert s.loc["ES", "on_weekends"] == 0.0  # 2 June 2025 is a Monday
    assert s.loc["ES", "in_spring"] == 0.0
    assert (s["corr_solar"].loc[["ES"]] < -0.5).all()
    assert s["in_daylight"].isna().tolist() == [True, False]
    by_hour = eu.negative_by_hour(prices)
    assert by_hour.loc[12, "ES"] == 1.0
    assert by_hour.loc[20, "ES"] == 0.0


def test_incomplete_solar_zones_are_left_out() -> None:
    prices, solar = solar_day()
    solar["NL"] = solar["FR"] / 50
    prices["NL"] = prices["FR"]
    assert "NL" not in eu.relative_solar(solar)
    assert "NL" not in eu.solar_profile(solar)
    s = eu.negative_solar_summary(prices, solar)
    assert s["corr_solar"].isna().loc[["NL"]].all()


def test_resolution_periods_detect_hourly_values_on_a_15min_grid() -> None:
    # Day 1 hourly (60), day 2 on the 15-min grid with hourly-constant values, day 3 real 15-min.
    idx = grid(96 * 3, start="2025-09-28T22:00Z")
    hourly_steps = np.repeat(np.arange(24, dtype=float), 4)
    values = np.concatenate([hourly_steps, hourly_steps, np.arange(96, dtype=float)])
    res = np.array([60.0] * 96 + [15.0] * 192)
    frame = pd.DataFrame({"FR": values, "res_FR": res}, index=idx)
    r = eu.resolution_periods(frame).loc["FR"]
    assert r["last_60"] == pd.Timestamp("2025-09-29")
    assert r["first_15"] == pd.Timestamp("2025-09-30")
    assert r["days_15"] == 2
    assert r["hourly_values_on_15min_days"] == 1


def test_zone_helpers_follow_price_zone_order() -> None:
    p = prices_frame({z: [1.0] for z in reversed(PRICE_ZONES)})
    assert eu.zones(p) == list(PRICE_ZONES)
    assert eu.neighbours(p) == list(PRICE_ZONES)[1:]
