from __future__ import annotations

from collections.abc import Callable
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from frgrid.dashboard import data as dd
from frgrid.dashboard import figures as ff
from frgrid.style import SOURCE
from synthetic import synthetic_inputs

INP = synthetic_inputs(days=200)
assert INP.flows is not None
FLOWS: pd.DataFrame = INP.flows
BT = dd.run_backtest(INP.prices, INP.load)

BUILDERS: dict[str, Callable[[], Any]] = {
    "price_profile": lambda: ff.price_profile(dd.price_profile(INP.prices), "Jan - Jul 2025"),
    "monthly_prices": lambda: ff.monthly_prices(dd.monthly_prices(INP.prices)),
    "forecast_vs_actual": lambda: ff.forecast_vs_actual(dd.backtest_monthly(BT)),
    "load_vs_forecast": lambda: ff.load_vs_forecast(dd.load_monthly(INP.load)),
    "residual_load": lambda: ff.residual_load(dd.residual_monthly(INP.load, INP.generation)),
    "generation_mix": lambda: ff.generation_mix(dd.generation_monthly(INP.generation)),
    "renewables_co2": lambda: ff.renewables_co2(dd.renewables_co2_monthly(INP.generation)),
    "net_position": lambda: ff.net_position(dd.net_position_monthly(FLOWS)),
    "border_flows": lambda: ff.border_flows(dd.border_flows(FLOWS), "Jan - Jul 2025"),
}


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_every_figure_builds_and_carries_the_source_line(name: str) -> None:
    fig = BUILDERS[name]()
    try:
        texts = [t.get_text() for t in fig.texts]
        assert SOURCE in texts
        assert fig.axes
        assert all(
            ax.get_ylabel() or ax.get_xlabel() for ax in fig.axes if ax.get_label() != "<colorbar>"
        )
    finally:
        plt.close(fig)
