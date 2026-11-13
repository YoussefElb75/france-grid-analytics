from __future__ import annotations

from collections.abc import Callable
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from frgrid import europe as eu
from frgrid import europe_figures as ef
from frgrid.style import SOURCE
from synthetic import synthetic_europe, synthetic_inputs

EU = synthetic_europe(days=70)
P, SOLAR, CAP = EU["eu_prices"], EU["eu_solar"], EU["eu_capacity"]
_flows = synthetic_inputs(days=70).flows
assert _flows is not None
FLOWS: pd.DataFrame = _flows
SPR = eu.spreads(P)
PERIOD = "Jan - Mar 2025"

BUILDERS: dict[str, Callable[[], Any]] = {
    "price_heatmap": lambda: ef.price_heatmap(eu.monthly_mean_prices(P)),
    "negative_heatmap": lambda: ef.negative_heatmap(eu.negative_by_month(P)),
    "spread_distribution": lambda: ef.spread_distribution(eu.spread_distribution(SPR), PERIOD),
    "spread_by_hour": lambda: ef.spread_by_hour(eu.spread_by_hour(SPR), PERIOD),
    "spread_by_month": lambda: ef.spread_by_month(eu.spread_by_month(SPR)),
    "convergence_by_month": lambda: ef.convergence_by_month(eu.convergence_by_month(P)),
    "flow_vs_spread": lambda: ef.flow_vs_spread(eu.flow_vs_spread(P, FLOWS), PERIOD),
    "against_by_spread_size": lambda: ef.against_by_spread_size(
        eu.against_by_spread_size(P, FLOWS), PERIOD
    ),
    "negative_vs_solar": lambda: ef.negative_vs_solar(
        eu.negative_by_hour(P), eu.solar_profile(SOLAR), PERIOD
    ),
    "congestion_by_month": lambda: ef.congestion_by_month(eu.congestion_by_month(CAP)),
}


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_every_european_figure_builds_and_carries_the_source_line(name: str) -> None:
    fig = BUILDERS[name]()
    try:
        assert SOURCE in [t.get_text() for t in fig.texts]
        axes = [ax for ax in fig.axes if ax.get_label() != "<colorbar>"]
        assert axes
        assert all(ax.get_ylabel() or ax.get_xlabel() or ax.get_yticklabels() for ax in axes)
    finally:
        plt.close(fig)


def test_zone_colours_do_not_depend_on_which_zones_are_shown() -> None:
    full = ef.spread_by_hour(eu.spread_by_hour(SPR), PERIOD)
    part = ef.spread_by_hour(eu.spread_by_hour(SPR[["ES"]]), PERIOD)
    try:
        colour = {ln.get_label(): ln.get_color() for ln in full.axes[0].get_lines()}
        assert part.axes[0].get_lines()[0].get_color() == colour["Spain"]
    finally:
        plt.close(full)
        plt.close(part)
