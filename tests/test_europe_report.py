from __future__ import annotations

from pathlib import Path

import pandas as pd

from frgrid import europe_report as er
from synthetic import synthetic_europe, synthetic_inputs


def inputs(days: int = 160) -> er.EuropeInputs:
    eu = synthetic_europe(days=days)
    flows = synthetic_inputs(days=days).flows
    assert flows is not None
    return er.EuropeInputs(eu["eu_prices"], flows, eu["eu_solar"], eu["eu_capacity"])


def test_report_keeps_complete_months_only() -> None:
    # 160 days from 1 Jan 2025 (UTC) end on 9 June: May is the last complete month.
    inp = er.trim(inputs())
    last = pd.DatetimeIndex(inp.prices.index).tz_convert("Europe/Paris").max()
    assert (last.year, last.month) == (2025, 5)
    assert er.period_of(inp.prices) == "Jan 2025 - May 2025"


def test_complete_month_is_kept_when_data_reach_its_end() -> None:
    idx = pd.date_range(
        "2025-01-31T23:00Z", "2025-02-28T22:45Z", freq="15min", tz="UTC", name="time_utc"
    )
    frame = pd.DataFrame({"FR": 1.0}, index=idx)
    assert er.complete_months_end(frame) == pd.Timestamp("2025-02-28T23:00Z")


def test_build_writes_four_charts_and_tables(tmp_path: Path) -> None:
    paths, md = er.build(inputs(), tmp_path)
    assert [p.name for p in paths] == [
        "eu_price_heatmap.png",
        "eu_spread_by_hour.png",
        "eu_flow_vs_spread.png",
        "eu_negative_solar.png",
    ]
    for p in paths:
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    for heading in ("Mean day-ahead price", "convergence", "Physical flow", "Congestion",
                    "Negative prices", "Published resolution"):  # fmt: skip
        assert heading in md
    assert "| Netherlands |" in md
