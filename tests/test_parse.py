from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from frgrid.parse import (
    AcknowledgementError,
    ParseError,
    expand,
    parse_document,
    parse_resolution,
)

FIX = Path(__file__).parent / "fixtures"


def read(name: str) -> bytes:
    return (FIX / name).read_bytes()


def doc(
    points: str, curve: str = "A03", res: str = "PT60M", end: str = "2025-01-01T04:00Z"
) -> bytes:
    return f"""<?xml version="1.0"?>
<Publication_MarketDocument xmlns="urn:x">
  <TimeSeries><curveType>{curve}</curveType>
    <Period><timeInterval><start>2025-01-01T00:00Z</start><end>{end}</end></timeInterval>
      <resolution>{res}</resolution>{points}</Period>
  </TimeSeries>
</Publication_MarketDocument>""".encode()


def pt(pos: int, value: float) -> str:
    return f"<Point><position>{pos}</position><quantity>{value}</quantity></Point>"


@pytest.mark.parametrize(
    ("text", "minutes"), [("PT15M", 15), ("PT60M", 60), ("PT1H", 60), ("PT30M", 30), ("P1D", 1440)]
)
def test_parse_resolution(text: str, minutes: int) -> None:
    assert parse_resolution(text) == pd.Timedelta(minutes=minutes)


@pytest.mark.parametrize("text", ["", "P", "PT", "1H", "P1M"])
def test_parse_resolution_rejects(text: str) -> None:
    with pytest.raises(ParseError):
        parse_resolution(text)


def test_a03_forward_fills_omitted_positions() -> None:
    (ts,) = parse_document(doc(pt(1, 10) + pt(3, 30)), "quantity")
    assert ts.values.tolist() == [10.0, 10.0, 30.0, 30.0]
    assert str(pd.DatetimeIndex(ts.values.index).tz) == "UTC"
    assert ts.values.index[0] == pd.Timestamp("2025-01-01T00:00Z")


def test_a01_leaves_missing_positions_empty() -> None:
    (ts,) = parse_document(doc(pt(1, 10) + pt(3, 30), curve="A01"), "quantity")
    assert np.isnan(ts.values.iloc[1])
    assert np.isnan(ts.values.iloc[3])


def test_a03_without_first_position_is_an_error() -> None:
    with pytest.raises(ParseError):
        parse_document(doc(pt(2, 10)), "quantity")


def test_position_outside_period_is_an_error() -> None:
    with pytest.raises(ParseError):
        parse_document(doc(pt(1, 1) + pt(5, 1)), "quantity")


def test_period_must_be_whole_slots() -> None:
    with pytest.raises(ParseError):
        parse_document(doc(pt(1, 1), end="2025-01-01T04:10Z"), "quantity")


def test_real_15min_prices_fill_96_quarter_hours() -> None:
    (ts,) = parse_document(read("prices_pt15m.xml"), "price.amount")
    assert ts.resolution == pd.Timedelta(minutes=15)
    assert len(ts.values) == 96  # the document lists 95 points (A03 compression)
    assert ts.values.notna().all()
    assert ts.meta["contract_MarketAgreement.type"] == "A01"


def test_real_hourly_prices() -> None:
    (ts,) = parse_document(read("prices_pt60m.xml"), "price.amount")
    assert ts.resolution == pd.Timedelta(hours=1)
    assert len(ts.values) == 24
    assert ts.values.index[0] == pd.Timestamp("2025-06-14T22:00Z")  # midnight in Paris (CEST)


def test_real_two_day_document_gives_two_series() -> None:
    series = parse_document(read("prices_transition.xml"), "price.amount")
    assert len(series) == 2
    assert all(len(s.values) == 96 for s in series)


def test_single_point_flow_spans_the_whole_day() -> None:
    (ts,) = parse_document(read("flows_import_CH.xml"), "quantity")
    assert len(ts.values) == 24
    assert ts.values.nunique() == 1


def test_generation_keeps_psr_and_direction_metadata() -> None:
    series = parse_document(read("generation.xml"), "quantity")
    kinds = {
        (s.meta["psrType"], "out" if "outBiddingZone_Domain.mRID" in s.meta else "in")
        for s in series
    }
    assert ("B10", "out") in kinds  # pumping
    assert ("B10", "in") in kinds  # turbining
    assert ("B14", "in") in kinds


def test_acknowledgement_no_data() -> None:
    with pytest.raises(AcknowledgementError) as info:
        parse_document(read("ack_no_data.xml"), "price.amount")
    assert info.value.no_data


def test_acknowledgement_error_is_not_mistaken_for_no_data() -> None:
    # ENTSO-E uses reason code 999 for this real error too.
    with pytest.raises(AcknowledgementError) as info:
        parse_document(read("ack_interval_too_large.xml"), "price.amount")
    assert info.value.code == "999"
    assert not info.value.no_data


def test_expand_hourly_to_quarter_hours_is_exact() -> None:
    idx = pd.date_range("2025-01-01", periods=2, freq="1h", tz="UTC")
    out = expand(pd.Series([1.0, 2.0], index=idx), pd.Timedelta(hours=1), pd.Timedelta(minutes=15))
    assert out.tolist() == [1.0] * 4 + [2.0] * 4
    assert out.index[1] - out.index[0] == pd.Timedelta(minutes=15)
    assert out.mean() == 1.5


def test_expand_rejects_non_divisors() -> None:
    idx = pd.date_range("2025-01-01", periods=1, freq="1h", tz="UTC")
    with pytest.raises(ValueError, match="cannot expand"):
        expand(pd.Series([1.0], index=idx), pd.Timedelta(hours=1), pd.Timedelta(minutes=25))


def test_mixed_resolution_periods_in_one_series() -> None:
    content = b"""<?xml version="1.0"?>
<GL_MarketDocument xmlns="urn:x"><TimeSeries><curveType>A01</curveType>
  <Period><timeInterval><start>2025-01-01T00:00Z</start><end>2025-01-01T01:00Z</end></timeInterval>
    <resolution>PT60M</resolution><Point><position>1</position><quantity>5</quantity></Point></Period>
  <Period><timeInterval><start>2025-01-01T01:00Z</start><end>2025-01-01T01:30Z</end></timeInterval>
    <resolution>PT15M</resolution><Point><position>1</position><quantity>7</quantity></Point>
    <Point><position>2</position><quantity>8</quantity></Point></Period>
</TimeSeries></GL_MarketDocument>"""
    (ts,) = parse_document(content, "quantity")
    assert ts.resolution == pd.Timedelta(minutes=15)
    assert ts.values.tolist() == [5.0, 5.0, 5.0, 5.0, 7.0, 8.0]
    assert ts.native_minutes.tolist() == [60.0] * 4 + [15.0] * 2
