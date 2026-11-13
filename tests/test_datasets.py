from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pandas as pd
import pytest

from frgrid import datasets
from frgrid.areas import FRANCE, NEIGHBOURS, PRICE_ZONES
from frgrid.client import EntsoeClient
from frgrid.parse import expand, parse_document

FIX = Path(__file__).parent / "fixtures"
DAY = (pd.Timestamp("2026-10-31T23:00Z"), pd.Timestamp("2026-11-01T23:00Z"))


class FakeClient:
    """Serves fixtures by query; records every query it receives."""

    def __init__(self, routes: Mapping[tuple[tuple[str, str], ...], str | None]) -> None:
        self.routes = routes
        self.calls: list[dict[str, str]] = []

    def get(
        self, params: Mapping[str, str], start: pd.Timestamp, end: pd.Timestamp
    ) -> bytes | None:
        self.calls.append(dict(params))
        for key, name in self.routes.items():
            if all(params.get(k) == v for k, v in key):
                return None if name is None else (FIX / name).read_bytes()
        return None


def as_client(fake: FakeClient) -> EntsoeClient:
    return cast(EntsoeClient, fake)


def test_windows_split_at_paris_quarter_starts() -> None:
    start = pd.Timestamp("2024-01-01", tz="Europe/Paris").tz_convert("UTC")
    end = pd.Timestamp("2025-01-01", tz="Europe/Paris").tz_convert("UTC")
    w = datasets.windows(start, end)
    assert len(w) == 4
    assert w[0][0] == start
    assert w[-1][1] == end
    assert w[1][0] == pd.Timestamp("2024-03-31T22:00Z")  # 1 April, Paris summer time
    assert all(a < b for a, b in w)


def test_windows_require_aware_increasing_bounds() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        datasets.windows(pd.Timestamp("2024-01-01"), pd.Timestamp("2024-02-01", tz="UTC"))
    with pytest.raises(ValueError, match="after start"):
        datasets.windows(DAY[1], DAY[0])


def test_prices_on_15min_grid_with_native_resolution() -> None:
    fake = FakeClient({(("documentType", "A44"),): "prices_pt15m.xml"})
    frame = datasets.day_ahead_prices(as_client(fake), *DAY)
    assert len(frame) == 96
    assert frame.index.name == "time_utc"
    assert str(pd.DatetimeIndex(frame.index).tz) == "UTC"
    assert frame["price_eur_mwh"].notna().all()
    assert set(frame["resolution_min"]) == {15.0}


def test_hourly_prices_are_repeated_on_the_15min_grid() -> None:
    day = (pd.Timestamp("2025-06-14T22:00Z"), pd.Timestamp("2025-06-15T22:00Z"))
    fake = FakeClient({(("documentType", "A44"),): "prices_pt60m.xml"})
    frame = datasets.day_ahead_prices(as_client(fake), *day)
    assert len(frame) == 96
    assert set(frame["resolution_min"]) == {60.0}
    hourly = frame["price_eur_mwh"].to_numpy().reshape(24, 4)
    assert (hourly == hourly[:, :1]).all()


def test_load_columns() -> None:
    fake = FakeClient(
        {
            (("documentType", "A65"), ("processType", "A16")): "load_actual.xml",
            (("documentType", "A65"), ("processType", "A01")): "load_forecast.xml",
        }
    )
    frame = datasets.load(as_client(fake), *DAY)
    assert list(frame.columns) == ["load_actual_mw", "load_forecast_mw"]
    assert frame.notna().all().all()
    assert 20_000 < frame["load_actual_mw"].mean() < 100_000


def test_generation_separates_pumping_from_production() -> None:
    fake = FakeClient({(("documentType", "A75"),): "generation.xml"})
    frame = datasets.generation(as_client(fake), *DAY)
    assert "Nuclear" in frame
    assert "Hydro Pumped Storage" in frame
    assert "Hydro Pumped Storage (consumption)" in frame
    assert (frame >= 0).all().all()


def test_flow_directions_follow_entsoe_in_out_domains() -> None:
    be = NEIGHBOURS["BE"]
    fake = FakeClient(
        {
            (("in_Domain", FRANCE), ("out_Domain", be)): "flows_import_BE.xml",
            (("in_Domain", be), ("out_Domain", FRANCE)): "flows_export_BE.xml",
        }
    )
    frame = datasets.physical_flows(as_client(fake), *DAY)
    assert list(frame.columns) == [f"{d}_{c}" for c in NEIGHBOURS for d in ("import", "export")]
    imports = [c for c in fake.calls if c["in_Domain"] == FRANCE]
    exports = [c for c in fake.calls if c["out_Domain"] == FRANCE]
    assert len(imports) == len(exports) == len(NEIGHBOURS)
    expected_import = expand(
        parse_document((FIX / "flows_import_BE.xml").read_bytes(), "quantity")[0].values,
        pd.Timedelta(minutes=15),
        datasets.GRID,
    )
    pd.testing.assert_series_equal(
        frame["import_BE"], expected_import.rename("import_BE"), check_freq=False
    )
    assert frame["import_DE"].isna().all()  # no fixture served -> no data, not zeros


def test_budget_stops_between_requests() -> None:
    fake = FakeClient({})
    budget = datasets.Budget(deadline=0.0, clock=lambda: 1.0)
    with pytest.raises(datasets.BudgetExceededError):
        datasets.load(as_client(fake), *DAY, budget)
    assert fake.calls == []


def test_de_lu_keeps_the_sdac_sequence_only() -> None:
    # Fixture: sequence 2 (separate 15-min auction) comes first with synthetic base 80, sequence 1
    # (SDAC) second with base 88; values are base + 0.5 * position.
    fake = FakeClient({(("documentType", "A44"),): "prices_de_lu_two_sequences.xml"})
    frame = datasets.zone_prices(as_client(fake), PRICE_ZONES["DE_LU"], *DAY)
    assert fake.calls[0]["in_Domain"] == fake.calls[0]["out_Domain"] == PRICE_ZONES["DE_LU"]
    assert frame["price_eur_mwh"].iloc[0] == 88.5
    assert frame["price_eur_mwh"].notna().all()
    assert set(frame["resolution_min"]) == {15.0}


def test_spain_drops_intraday_auction_series() -> None:
    # Fixture: one day-ahead series (A01, base 50) and three intraday auctions (A07, base 55-65).
    fake = FakeClient({(("documentType", "A44"),): "prices_es_with_intraday.xml"})
    frame = datasets.zone_prices(as_client(fake), PRICE_ZONES["ES"], *DAY)
    parsed = parse_document((FIX / "prices_es_with_intraday.xml").read_bytes(), "price.amount")
    assert [s.meta.get("contract_MarketAgreement.type") for s in parsed] == ["A01"] + ["A07"] * 3
    expected = parsed[0].values.reindex(frame.index)
    pd.testing.assert_series_equal(
        frame["price_eur_mwh"], expected, check_names=False, check_freq=False
    )
    assert frame["price_eur_mwh"].iloc[0] == 50.25


def test_nl_transition_day_keeps_hourly_then_quarter_hourly() -> None:
    days = (pd.Timestamp("2025-09-29T22:00Z"), pd.Timestamp("2025-10-01T22:00Z"))
    fake = FakeClient({(("documentType", "A44"),): "prices_nl_transition.xml"})
    frame = datasets.zone_prices(as_client(fake), PRICE_ZONES["NL"], *days)
    assert frame["price_eur_mwh"].notna().all()
    res = frame["resolution_min"]
    assert set(res.iloc[:96]) == {60.0}
    assert set(res.iloc[96:]) == {15.0}


def test_european_prices_one_column_per_zone() -> None:
    fake = FakeClient({(("documentType", "A44"),): "prices_pt15m.xml"})
    frame = datasets.european_prices(as_client(fake), *DAY)
    zones = list(PRICE_ZONES)
    assert list(frame.columns) == [c for z in zones for c in (z, f"res_{z}")]
    assert [c["in_Domain"] for c in fake.calls] == list(PRICE_ZONES.values())
    assert frame[zones].notna().all().all()


def test_france_prices_reuse_the_v1_query() -> None:
    fake = FakeClient({})
    datasets.day_ahead_prices(as_client(fake), *DAY)
    datasets.european_prices(as_client(fake), *DAY)
    v1_query = {"documentType": "A44", "in_Domain": FRANCE, "out_Domain": FRANCE}
    assert fake.calls[0] == fake.calls[1] == v1_query


def test_solar_per_zone_drops_the_consumption_series() -> None:
    # Fixture: series 1 is reported against outBiddingZone (consumption, base 1000), series 2
    # against inBiddingZone (generation, base 1100); values are base + 10 * position.
    day = (pd.Timestamp("2025-06-14T22:00Z"), pd.Timestamp("2025-06-15T22:00Z"))
    fake = FakeClient(
        {(("documentType", "A75"), ("psrType", "B16")): "solar_nl_with_consumption.xml"}
    )
    frame = datasets.european_solar(as_client(fake), *day)
    assert list(frame.columns) == list(PRICE_ZONES)
    assert all(c["psrType"] == "B16" and c["processType"] == "A16" for c in fake.calls)
    assert [c["in_Domain"] for c in fake.calls] == list(PRICE_ZONES.values())
    parsed = parse_document((FIX / "solar_nl_with_consumption.xml").read_bytes(), "quantity")
    generation = next(s for s in parsed if "inBiddingZone_Domain.mRID" in s.meta)
    expected = generation.values.reindex(frame.index)
    pd.testing.assert_series_equal(frame["NL"], expected, check_names=False, check_freq=False)
    assert frame["NL"].min() >= 1100
