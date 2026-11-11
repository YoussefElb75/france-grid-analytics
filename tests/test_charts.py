from __future__ import annotations

from pathlib import Path

from frgrid import charts
from synthetic import synthetic_inputs


def test_build_writes_all_charts_and_a_results_table(tmp_path: Path) -> None:
    paths, results = charts.build(synthetic_inputs(), tmp_path)
    assert {p.name for p in paths} == {
        "price_profile.png",
        "generation_mix.png",
        "residual_load_price.png",
        "renewables_co2.png",
        "forecast_mae.png",
        "net_exports.png",
    }
    for p in paths:
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert "| MAE (EUR/MWh) |" in results
    assert "Diebold-Mariano" in results


def test_build_without_flows_skips_that_chart(tmp_path: Path) -> None:
    inp = synthetic_inputs()
    paths, _ = charts.build(charts.Inputs(inp.prices, inp.load, inp.generation, None), tmp_path)
    assert "net_exports.png" not in {p.name for p in paths}
