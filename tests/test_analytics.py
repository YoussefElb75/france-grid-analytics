from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from frgrid import analytics as an


def grid(n: int, start: str = "2025-01-06T00:00Z", freq: str = "15min") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq=freq, tz="UTC", name="time_utc")


def gen_frame(n: int = 4) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Nuclear": 600.0,
            "Wind Onshore": 200.0,
            "Solar": 100.0,
            "Fossil Gas": 100.0,
            "Hydro Pumped Storage": 50.0,  # storage output: excluded
            "Hydro Pumped Storage (consumption)": 80.0,  # pumping: excluded
        },
        index=grid(n),
    )


def test_hourly_requires_four_quarter_hours() -> None:
    s = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0, np.nan, 7.0, 8.0]}, index=grid(8))
    out = an.hourly(s)
    assert out["x"].iloc[0] == 2.5
    assert np.isnan(out["x"].iloc[1])


def test_total_generation_excludes_storage_and_consumption() -> None:
    assert (an.total_generation(gen_frame()) == 1000.0).all()


def test_renewable_share() -> None:
    assert an.renewable_share(gen_frame()).iloc[0] == pytest.approx(0.3)


def test_residual_load() -> None:
    load = pd.DataFrame({"load_actual_mw": 1100.0}, index=grid(4))
    assert (an.residual_load(load, gen_frame()) == 800.0).all()


def test_co2_intensity_is_generation_weighted() -> None:
    expected = (600 * 12 + 200 * 11 + 100 * 48 + 100 * 490) / 1000
    assert an.co2_intensity(gen_frame()).iloc[0] == pytest.approx(expected)


def test_co2_intensity_refuses_unknown_types() -> None:
    frame = gen_frame().assign(Mystery=1.0)
    with pytest.raises(KeyError, match="Mystery"):
        an.co2_intensity(frame)


def test_every_known_production_type_has_a_sourced_factor() -> None:
    for name, factor in an.EMISSION_FACTORS.items():
        assert factor.g_per_kwh > 0, name
        assert factor.source


def test_net_imports_sign_convention() -> None:
    flows = pd.DataFrame(
        {"import_BE": 100.0, "export_BE": 300.0, "import_GB": 50.0, "export_GB": 0.0}, index=grid(2)
    )
    net = an.net_imports(flows)
    assert net["BE"].iloc[0] == -200.0  # France exports to Belgium
    assert net["GB"].iloc[0] == 50.0
    assert net["total"].iloc[0] == -150.0


def test_daily_profile_uses_paris_local_hours() -> None:
    idx = grid(24 * 365, start="2025-01-01T00:00Z", freq="1h")
    s = pd.Series(np.where(idx.hour == 10, 1.0, 0.0), index=idx)  # 10:00 UTC
    prof = an.daily_profile(s)
    assert prof.loc[11, "winter"] == pytest.approx(1.0)  # 11:00 CET
    assert prof.loc[12, "summer"] == pytest.approx(1.0)  # 12:00 CEST
    assert list(prof.columns) == ["winter", "spring", "summer", "autumn"]


def test_daily_profile_by_daytype() -> None:
    idx = grid(24 * 14, start="2025-01-06T00:00Z", freq="1h")
    s = pd.Series(1.0, index=idx)
    assert list(an.daily_profile(s, by="daytype").columns) == ["weekday", "saturday", "sunday"]
    with pytest.raises(ValueError, match="unknown grouping"):
        an.daily_profile(s, by="moon")


def test_missing_core_type_makes_the_timestamp_missing() -> None:
    frame = gen_frame()
    frame.loc[frame.index[1], "Nuclear"] = np.nan
    frame["Fossil Hard coal"] = np.nan  # minor type not reported: counts as 0
    total = an.total_generation(frame)
    assert np.isnan(total.iloc[1])
    assert total.iloc[0] == 1000.0
    assert np.isnan(an.renewable_share(frame).iloc[1])
    assert np.isnan(an.co2_intensity(frame).iloc[1])
