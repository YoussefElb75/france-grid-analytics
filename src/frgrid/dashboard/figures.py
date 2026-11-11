"""Matplotlib figures for the dashboard, in the same style as the README charts.

Every builder takes an aggregated table from :mod:`frgrid.dashboard.data` and returns a figure
whose footer carries the ENTSO-E source line.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from frgrid.style import SERIES, SURFACE, TEXT_2, label_line_ends, layout, new_figure

SEASON_LABELS = {"winter": "Winter", "spring": "Spring", "summer": "Summer", "autumn": "Autumn"}


def _period(index: pd.Index[Any]) -> str:
    idx = pd.DatetimeIndex(index)
    return f"{idx.min():%b %Y} - {idx.max():%b %Y}"


def _month_axis(ax: Any, index: pd.Index[Any]) -> None:
    idx = pd.DatetimeIndex(index)
    if len(idx) > 1:
        ax.set_xlim(idx[0], idx[-1])


def price_profile(prof: pd.DataFrame, period: str) -> Any:
    fig, (ax,) = new_figure(
        "Average day-ahead price by hour of day",
        f"EUR/MWh, mean per local hour and season, {period}",
    )
    named = prof.rename(columns=SEASON_LABELS)
    for i, col in enumerate(named.columns):
        ax.plot(named.index, named[col], color=SERIES[i], label=col)
    label_line_ends(ax, named)
    ax.set_xticks(range(0, 24, 3), [f"{h:02d}:00" for h in range(0, 24, 3)])
    ax.set_xlim(0, 23)
    ax.set_ylabel("EUR/MWh")
    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0, 1.1))
    return layout(fig, top=0.8)


def monthly_prices(table: pd.DataFrame) -> Any:
    fig, (ax,) = new_figure(
        "Monthly day-ahead price",
        "Mean of hourly prices with the 10th-90th percentile band, EUR/MWh, "
        + _period(table.index),
    )
    x = pd.DatetimeIndex(table.index)
    ax.fill_between(
        x, table["p10"], table["p90"], color=SERIES[0], alpha=0.18, linewidth=0, label="P10-P90"
    )
    ax.plot(x, table["mean"], color=SERIES[0], marker="o", markersize=4, label="Mean")
    ax.axhline(0, color=TEXT_2, linewidth=0.8)
    _month_axis(ax, x)
    ax.set_ylabel("EUR/MWh")
    ax.legend(ncol=2, loc="upper left", bbox_to_anchor=(0, 1.1))
    return layout(fig, top=0.8)


def forecast_vs_actual(table: pd.DataFrame) -> Any:
    fig, (ax1, ax2) = new_figure(
        "Day-ahead price forecast vs actual (walk-forward backtest)",
        "Top: monthly mean of actual and forecast hourly prices. Bottom: mean absolute error.",
        nrows=2,
        height=6.0,
    )
    x = pd.DatetimeIndex(table.index)
    ax1.plot(x, table["actual_mean"], color=SERIES[0], marker="o", markersize=4, label="Actual")
    ax1.plot(
        x, table["model_mean"], color=SERIES[1], marker="o", markersize=4, label="Forecast (ridge)"
    )
    ax1.set_ylabel("EUR/MWh")
    ax1.legend(ncol=2, loc="upper left", bbox_to_anchor=(0, 1.22))
    names = {"mae_model": "Ridge model", "mae_naive_d1": "Naive D-1", "mae_naive_d7": "Naive D-7"}
    for i, col in enumerate(names):
        ax2.plot(x, table[col], color=SERIES[i], marker="o", markersize=4, label=names[col])
    ax2.set_ylabel("MAE, EUR/MWh")
    ax2.set_ylim(bottom=0)
    ax2.legend(ncol=3, loc="upper left", bbox_to_anchor=(0, 1.22))
    _month_axis(ax2, x)
    fig.subplots_adjust(hspace=0.45)
    return layout(fig, top=0.82)


def load_vs_forecast(table: pd.DataFrame) -> Any:
    fig, (ax1, ax2) = new_figure(
        "Load vs the TSO's day-ahead forecast",
        "Top: monthly mean load, GW. Bottom: mean absolute error of the hourly forecast, GW.",
        nrows=2,
        height=6.0,
    )
    x = pd.DatetimeIndex(table.index)
    ax1.plot(x, table["actual_gw"], color=SERIES[0], marker="o", markersize=4, label="Actual")
    ax1.plot(
        x,
        table["forecast_gw"],
        color=SERIES[1],
        marker="o",
        markersize=4,
        linestyle="--",
        label="Day-ahead forecast",
    )
    ax1.set_ylabel("GW")
    ax1.legend(ncol=2, loc="upper left", bbox_to_anchor=(0, 1.22))
    ax2.bar(x, table["forecast_mae_gw"], width=20, color=SERIES[0], edgecolor=SURFACE)
    ax2.set_ylabel("MAE, GW")
    _month_axis(ax2, x)
    fig.subplots_adjust(hspace=0.45)
    return layout(fig, top=0.82)


def residual_load(table: pd.DataFrame) -> Any:
    fig, (ax,) = new_figure(
        "Load, wind + solar, and residual load",
        f"Monthly means, GW, {_period(table.index)}",
    )
    names = {"load_gw": "Load", "residual_gw": "Residual load", "wind_solar_gw": "Wind + solar"}
    x = pd.DatetimeIndex(table.index)
    for i, col in enumerate(names):
        ax.plot(x, table[col], color=SERIES[i], marker="o", markersize=4, label=names[col])
    label_line_ends(ax, table[list(names)].rename(columns=names).set_index(x))
    ax.set_ylim(bottom=0)
    ax.set_ylabel("GW")
    _month_axis(ax, x)
    ax.legend(ncol=3, loc="upper left", bbox_to_anchor=(0, 1.1))
    return layout(fig, top=0.8)


def generation_mix(table: pd.DataFrame) -> Any:
    fig, (ax,) = new_figure(
        "Monthly generation mix",
        f"Average generation in GW by production type, {_period(table.index)}",
    )
    x = pd.DatetimeIndex(table.index)
    ax.stackplot(
        x,
        [table[c] for c in table.columns],
        colors=SERIES[: len(table.columns)],
        labels=list(table.columns),
        edgecolor=SURFACE,
        linewidth=1.0,
    )
    mids = table.cumsum(axis=1) - table / 2
    for name in ("Nuclear", "Hydro", "Wind"):
        if name in table:
            ax.annotate(
                name,
                xy=(x[-1], float(mids[name].iloc[-1])),
                xytext=(8, 0),
                textcoords="offset points",
                va="center",
                fontsize=9,
                annotation_clip=False,
            )
    ax.set_ylabel("GW")
    _month_axis(ax, x)
    ax.legend(ncol=6, loc="upper left", bbox_to_anchor=(0, 1.1))
    return layout(fig, top=0.8)


def renewables_co2(table: pd.DataFrame) -> Any:
    fig, (ax1, ax2) = new_figure(
        "Renewable share and carbon intensity of French generation",
        f"Monthly means of hourly values, {_period(table.index)}",
        nrows=2,
        height=5.6,
    )
    x = pd.DatetimeIndex(table.index)
    ax1.plot(x, table["renewable_share_pct"], color=SERIES[0], marker="o", markersize=4)
    ax1.set_ylabel("renewable share, %")
    ax2.plot(x, table["co2_g_per_kwh"], color=SERIES[1], marker="o", markersize=4)
    ax2.set_ylabel("gCO2eq/kWh (life cycle)")
    for ax in (ax1, ax2):
        ax.set_ylim(bottom=0)
    _month_axis(ax2, x)
    fig.subplots_adjust(hspace=0.25)
    return layout(fig, top=0.86)


def net_position(table: pd.DataFrame) -> Any:
    order = table.mean().sort_values(ascending=False).index
    t = table[order]
    fig, (ax,) = new_figure(
        "Net position per border",
        f"Net physical exports, monthly mean in GW (negative = net imports), {_period(t.index)}",
    )
    x = np.arange(len(t))
    pos = np.zeros(len(t))
    neg = np.zeros(len(t))
    for i, border in enumerate(t.columns):
        v = t[border].fillna(0.0).to_numpy()
        ax.bar(x, v, bottom=np.where(v >= 0, pos, neg), width=0.78, color=SERIES[i],
               label=border, edgecolor=SURFACE, linewidth=0.8)  # fmt: skip
        pos += np.where(v >= 0, v, 0)
        neg += np.where(v < 0, v, 0)
    ax.axhline(0, color=TEXT_2, linewidth=0.8)
    idx = pd.DatetimeIndex(t.index)
    step = max(1, len(idx) // 8)
    ticks = list(range(0, len(idx), step))
    ax.set_xticks(ticks, [f"{idx[i]:%b %Y}" for i in ticks])
    ax.set_ylabel("GW")
    ax.legend(title="border", loc="upper left", bbox_to_anchor=(1.01, 0.9))
    return layout(fig)


def border_flows(table: pd.DataFrame, period: str) -> Any:
    fig, (ax,) = new_figure(
        "Imports and exports per border",
        f"Mean physical flow, GW, {period}. Import = into France; export = out of France.",
    )
    y = np.arange(len(table))
    ax.barh(y, -table["import_gw"], color=SERIES[1], label="Import into France", edgecolor=SURFACE)
    ax.barh(y, table["export_gw"], color=SERIES[0], label="Export from France", edgecolor=SURFACE)
    for i, (imp, exp) in enumerate(zip(table["import_gw"], table["export_gw"], strict=True)):
        ax.annotate(
            f"{exp:.2f}",
            xy=(exp, i),
            xytext=(4, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
        )
        ax.annotate(
            f"{imp:.2f}",
            xy=(-imp, i),
            xytext=(-4, 0),
            textcoords="offset points",
            va="center",
            ha="right",
            fontsize=9,
        )
    ax.set_yticks(y, list(table.index))
    ax.invert_yaxis()
    ax.axvline(0, color=TEXT_2, linewidth=0.8)
    lim = float(max(table["import_gw"].max(), table["export_gw"].max())) * 1.25
    ax.set_xlim(-lim, lim)
    ax.set_xlabel("GW (imports shown to the left)")
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    ax.legend(ncol=2, loc="upper left", bbox_to_anchor=(0, 1.1))
    return layout(fig, top=0.8)
