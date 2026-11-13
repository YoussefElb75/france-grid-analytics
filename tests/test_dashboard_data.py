from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path
from types import TracebackType

import pandas as pd
import pytest

from frgrid import store
from frgrid.client import EntsoeClient, EntsoeError
from frgrid.dashboard import data as dd
from synthetic import synthetic_europe, synthetic_inputs

FIX = Path(__file__).parent / "fixtures"


def save_all(fetched_at: pd.Timestamp | None = None) -> None:
    inp = synthetic_inputs(days=200)
    assert inp.flows is not None
    frames = {
        "prices": inp.prices,
        "load": inp.load,
        "generation": inp.generation,
        "flows": inp.flows,
    }
    for name, frame in frames.items():
        store.save(name, frame, fetched_at=fetched_at)


class FakeClient:
    """Context-manager client that serves the 15-minute price fixture and no data otherwise."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(
        self, t: type[BaseException] | None, e: BaseException | None, tb: TracebackType | None
    ) -> None:
        return None

    def get(self, params: dict[str, str], start: pd.Timestamp, end: pd.Timestamp) -> bytes | None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if params.get("documentType") == "A44":
            return (FIX / "prices_pt15m.xml").read_bytes()
        return None


def factory(fake: FakeClient) -> EntsoeClient:
    return fake  # type: ignore[return-value]


# ---- bundle and freshness ---------------------------------------------------------------------


def test_empty_store_gives_an_empty_bundle() -> None:
    bundle = dd.load_bundle()
    assert bundle.is_empty
    assert bundle.missing == list(dd.NAMES)
    assert bundle.as_of is None
    assert not bundle.fetched_in_session
    assert dd.format_as_of(bundle.as_of) == "unknown"
    assert dd.month_options(bundle) == []


def test_bundle_reports_oldest_fetch_time_and_is_never_live_from_disk() -> None:
    save_all(fetched_at=pd.Timestamp("2026-11-01T10:00Z"))
    save_europe()
    store.save(
        "prices", synthetic_inputs(days=200).prices, fetched_at=pd.Timestamp("2026-11-05T10:00Z")
    )
    bundle = dd.load_bundle()
    assert bundle.available == list(dd.NAMES)
    assert bundle.as_of == pd.Timestamp("2026-11-01T10:00Z")
    assert not bundle.fetched_in_session
    assert dd.format_as_of(bundle.as_of) == "2026-11-01 11:00 (Europe/Paris)"


def test_partial_store_lists_missing_datasets() -> None:
    store.save("prices", synthetic_inputs(days=200).prices)
    bundle = dd.load_bundle()
    assert bundle.available == ["prices"]
    assert bundle.missing == ["load", "generation", "flows", "eu_prices", "eu_solar", "eu_capacity"]


def test_meta_falls_back_to_file_time() -> None:
    store.save("load", synthetic_inputs(days=200).load)
    store.meta_path_for("load").unlink()
    meta = store.read_meta("load")
    assert meta is not None
    assert abs(meta.fetched_at - pd.Timestamp.now(tz="UTC")) < pd.Timedelta(minutes=5)


def test_store_signature_changes_on_save() -> None:
    before = dd.store_signature()
    store.save("prices", synthetic_inputs(days=200).prices)
    after = dd.store_signature()
    assert before != after
    assert os.sep not in after  # file names only, no paths


def test_coverage_and_month_options() -> None:
    save_all()
    bundle = dd.load_bundle()
    cov = bundle.coverage()
    assert cov is not None
    assert str(cov[0].tz) == "Europe/Paris"
    months = dd.month_options(bundle)
    assert months[0] == pd.Timestamp("2025-01-01")
    assert len(months) == 7


# ---- refresh ----------------------------------------------------------------------------------


def test_refresh_marks_the_bundle_as_fetched_in_session() -> None:
    fake = FakeClient()
    bundle = dd.refresh(date(2026, 11, 1), date(2026, 11, 2), client_factory=lambda: factory(fake))
    assert bundle.fetched_in_session
    assert fake.calls > 0
    assert set(bundle.available) == set(dd.NAMES)
    prices = bundle.get("prices")
    assert prices is not None
    assert prices["price_eur_mwh"].notna().sum() == 96
    meta = store.read_meta("prices")
    assert meta is not None
    assert meta.start == pd.Timestamp("2026-10-31T23:00Z")


def test_refresh_without_token_gives_a_safe_message() -> None:
    with pytest.raises(dd.DataError, match=r"\.env"):
        dd.refresh(date(2026, 11, 1), date(2026, 11, 2))


def test_refresh_wraps_entsoe_errors(token_value: str) -> None:
    fake = FakeClient(EntsoeError("ENTSO-E HTTP 503 for documentType=A44"))
    with pytest.raises(dd.DataError) as info:
        dd.refresh(date(2026, 11, 1), date(2026, 11, 2), client_factory=lambda: factory(fake))
    assert "prices" in str(info.value)
    assert token_value not in str(info.value)


def test_refresh_reports_time_budget() -> None:
    fake = FakeClient()
    with pytest.raises(dd.DataError, match="resumes"):
        dd.refresh(
            date(2026, 11, 1),
            date(2026, 11, 2),
            max_minutes=-1,
            client_factory=lambda: factory(fake),
        )


def test_refresh_rejects_reversed_dates() -> None:
    with pytest.raises(dd.DataError, match="after the start"):
        dd.refresh(
            date(2026, 11, 2), date(2026, 11, 1), client_factory=lambda: factory(FakeClient())
        )


# ---- aggregated tables -------------------------------------------------------------------------


def test_monthly_prices_table() -> None:
    table = dd.monthly_prices(synthetic_inputs(days=200).prices)
    assert list(table.columns) == ["mean", "p10", "p90", "negative_share"]
    assert (table["p10"] <= table["mean"]).all()
    assert (table["mean"] <= table["p90"]).all()
    assert table.index.name == "month"
    assert pd.DatetimeIndex(table.index).tz is None


def test_price_profile_has_24_local_hours() -> None:
    prof = dd.price_profile(synthetic_inputs(days=200).prices)
    assert list(prof.index) == list(range(24))


def test_backtest_tables() -> None:
    inp = synthetic_inputs(days=200)
    bt = dd.run_backtest(inp.prices, inp.load)
    monthly = dd.backtest_monthly(bt)
    assert {"actual_mean", "model_mean", "mae_model", "mae_naive_d1", "mae_naive_d7"} <= set(
        monthly
    )
    first, last = monthly.index[0], monthly.index[-1]
    summary = dd.backtest_summary(bt, first, last)
    assert list(summary.index) == ["MAE", "RMSE", "bias"]
    assert dd.backtest_summary(bt, pd.Timestamp("2030-01-01"), pd.Timestamp("2030-02-01")).empty


def test_load_and_residual_tables() -> None:
    inp = synthetic_inputs(days=200)
    load = dd.load_monthly(inp.load)
    assert (load["forecast_mae_gw"] >= 0).all()
    res = dd.residual_monthly(inp.load, inp.generation)
    assert (res["residual_gw"] < res["load_gw"]).all()
    pd.testing.assert_series_equal(
        res["residual_gw"], res["load_gw"] - res["wind_solar_gw"], check_names=False, atol=1e-9
    )


def test_generation_and_renewables_tables() -> None:
    gen = synthetic_inputs(days=200).generation
    mix = dd.generation_monthly(gen)
    assert list(mix.columns)[:3] == ["Nuclear", "Hydro", "Wind"]
    rc = dd.renewables_co2_monthly(gen)
    assert rc["renewable_share_pct"].between(0, 100).all()
    assert (rc["co2_g_per_kwh"] > 0).all()


def test_flow_tables_follow_entsoe_directions() -> None:
    idx = pd.date_range("2025-01-01", periods=96 * 40, freq="15min", tz="UTC", name="time_utc")
    flows = pd.DataFrame(
        0.0, index=idx, columns=[f"{d}_{c}" for c in ("BE", "ES") for d in ("import", "export")]
    )
    flows["import_ES"] = 2000.0  # Spain -> France
    flows["export_BE"] = 1000.0  # France -> Belgium
    totals = dd.border_flows(flows)
    assert totals.loc["ES", "import_gw"] == pytest.approx(2.0)
    assert totals.loc["ES", "net_export_gw"] == pytest.approx(-2.0)
    assert totals.loc["BE", "export_gw"] == pytest.approx(1.0)
    assert list(totals.index) == ["BE", "ES"]  # sorted by net exports
    net = dd.net_position_monthly(flows)
    assert (net["ES"] < 0).all()
    assert (net["BE"] > 0).all()


def test_clip_helpers() -> None:
    inp = synthetic_inputs(days=200)
    table = dd.monthly_prices(inp.prices)
    clipped = dd.clip_months(table, pd.Timestamp("2025-02-01"), pd.Timestamp("2025-03-01"))
    assert list(clipped.index) == [pd.Timestamp("2025-02-01"), pd.Timestamp("2025-03-01")]
    period = dd.clip_period(inp.prices, pd.Timestamp("2025-02-01"), pd.Timestamp("2025-02-01"))
    local = pd.DatetimeIndex(period.index).tz_convert("Europe/Paris")
    assert set(local.month) == {2}


def test_refresh_uses_real_time_budget_clock() -> None:
    # A generous budget must not trip on a fast fake client.
    t0 = time.monotonic()
    dd.refresh(date(2026, 11, 1), date(2026, 11, 2), client_factory=lambda: factory(FakeClient()))
    assert time.monotonic() - t0 < 60


def save_europe() -> None:
    for name, frame in synthetic_europe(days=200).items():
        store.save(name, frame, fetched_at=pd.Timestamp("2026-11-01T10:00Z"))


def test_europe_view_needs_european_prices() -> None:
    save_all()
    bundle = dd.load_bundle()
    assert "eu_prices" in bundle.missing
    assert dd.europe_view(bundle, pd.Timestamp("2025-01-01"), pd.Timestamp("2025-06-01")) is None


def test_europe_view_tables_follow_the_selected_months() -> None:
    save_all()
    save_europe()
    bundle = dd.load_bundle()
    assert bundle.missing == []
    view = dd.europe_view(bundle, pd.Timestamp("2025-02-01"), pd.Timestamp("2025-03-01"))
    assert view is not None
    assert list(view.monthly_prices.index) == [
        pd.Timestamp("2025-02-01"),
        pd.Timestamp("2025-03-01"),
    ]
    assert list(view.spread_by_hour.index) == list(range(24))
    assert view.flow_vs_spread is not None
    assert view.congestion_check is not None
    assert view.negative_summary is not None
    assert "NL" not in (view.solar_profile if view.solar_profile is not None else pd.DataFrame())


def test_europe_view_without_optional_datasets() -> None:
    store.save("eu_prices", synthetic_europe(days=60)["eu_prices"])
    view = dd.europe_view(dd.load_bundle(), pd.Timestamp("2025-01-01"), pd.Timestamp("2025-02-01"))
    assert view is not None
    assert view.flow_vs_spread is None
    assert view.solar_profile is None
    assert view.congestion_by_month is None


def test_europe_view_outside_the_data_is_none() -> None:
    store.save("eu_prices", synthetic_europe(days=60)["eu_prices"])
    bundle = dd.load_bundle()
    assert dd.europe_view(bundle, pd.Timestamp("2024-01-01"), pd.Timestamp("2024-03-01")) is None
