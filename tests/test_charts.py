from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from frgrid import charts
from frgrid.areas import NEIGHBOURS


def synthetic_inputs(days: int = 160, seed: int = 1) -> charts.Inputs:
    idx = pd.date_range("2025-01-01", periods=days * 96, freq="15min", tz="UTC", name="time_utc")
    rng = np.random.default_rng(seed)
    hour = idx.tz_convert("Europe/Paris").hour.to_numpy()
    n = len(idx)
    load = 50_000 + 8_000 * np.sin(2 * np.pi * hour / 24) + rng.normal(0, 2_000, n)
    solar = np.clip(6_000 * np.sin(np.pi * (hour - 6) / 12), 0, None)
    wind = 6_000 + rng.normal(0, 1_500, n)
    gen = pd.DataFrame(
        {
            "Nuclear": 38_000.0,
            "Fossil Gas": 3_000.0,
            "Hydro Run-of-river and poundage": 5_000.0,
            "Hydro Water Reservoir": 2_000.0,
            "Solar": solar,
            "Wind Onshore": wind,
            "Biomass": 700.0,
            "Hydro Pumped Storage (consumption)": 500.0,
        },
        index=idx,
    )
    price = 10 + 0.0015 * (load - solar - wind) + rng.normal(0, 5, n)
    flows = pd.DataFrame(
        {f"{d}_{c}": rng.uniform(0, 2_000, n) for c in NEIGHBOURS for d in ("import", "export")},
        index=idx,
    )
    return charts.Inputs(
        prices=pd.DataFrame({"price_eur_mwh": price, "resolution_min": 15.0}, index=idx),
        load=pd.DataFrame({"load_actual_mw": load, "load_forecast_mw": load * 1.01}, index=idx),
        generation=gen,
        flows=flows,
    )


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
