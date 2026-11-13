"""Synthetic 15-minute datasets shared by the chart and dashboard tests (no network)."""

from __future__ import annotations

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


def synthetic_europe(days: int = 160, seed: int = 2) -> dict[str, pd.DataFrame]:
    """Synthetic eu_prices, eu_solar and eu_capacity frames on the same grid as the inputs."""
    idx = pd.date_range("2025-01-01", periods=days * 96, freq="15min", tz="UTC", name="time_utc")
    rng = np.random.default_rng(seed)
    n = len(idx)
    hour = idx.tz_convert("Europe/Paris").hour.to_numpy()
    bell = np.clip(np.sin(np.pi * (hour - 6) / 12), 0, None)
    base = 60 + 20 * np.sin(2 * np.pi * hour / 24) - 70 * bell + rng.normal(0, 10, n)
    prices: dict[str, np.ndarray] = {"FR": base}
    for i, zone in enumerate(("DE_LU", "BE", "NL", "ES", "IT_NORTH")):
        coupled = rng.random(n) < 0.3
        prices[zone] = np.where(coupled, base, base + rng.normal(5 * i, 10, n))
    eu_prices = pd.DataFrame(prices, index=idx)
    for zone in prices:
        eu_prices[f"res_{zone}"] = 15.0
    solar = pd.DataFrame({z: 1_000 * (i + 1) * bell for i, z in enumerate(prices)}, index=idx)
    cap: dict[str, np.ndarray] = {}
    for zone in ("ES", "IT_NORTH"):
        cap[f"ntc_FR_to_{zone}"] = np.full(n, 3_000.0)
        cap[f"da_FR_to_{zone}"] = rng.choice([1_000.0, 3_000.0], n)
        cap[f"ntc_{zone}_to_FR"] = np.full(n, 2_000.0)
        cap[f"da_{zone}_to_FR"] = np.zeros(n)
    return {
        "eu_prices": eu_prices,
        "eu_solar": solar,
        "eu_capacity": pd.DataFrame(cap, index=idx),
    }
