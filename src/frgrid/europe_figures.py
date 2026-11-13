"""Figures for the European analysis, shared by the dashboard and the README report.

Each builder takes an aggregated table from :mod:`frgrid.europe` and returns a Matplotlib figure
that carries the ENTSO-E source line (see :func:`frgrid.style.new_figure`). Zones keep a fixed
colour (:data:`frgrid.style.ZONE_COLORS`) and are always named by a legend or a direct label.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

from frgrid.areas import ZONE_LABELS
from frgrid.style import (
    GRID,
    SEQUENTIAL,
    SERIES,
    SURFACE,
    TEXT,
    TEXT_2,
    ZONE_COLORS,
    layout,
    new_figure,
)

SEQ_CMAP = LinearSegmentedColormap.from_list("seq", SEQUENTIAL)
HOUR_TICKS = list(range(0, 24, 3))
LEFT_LABELS = 0.15  # room for zone names on the y axis


def _period(index: pd.Index[Any]) -> str:
    idx = pd.DatetimeIndex(index)
    return f"{idx.min():%b %Y} - {idx.max():%b %Y}"


def _label(zone: str) -> str:
    return ZONE_LABELS.get(zone, zone)


def _hour_axis(ax: Any) -> None:
    ax.set_xticks(HOUR_TICKS, [f"{h:02d}:00" for h in HOUR_TICKS])
    ax.set_xlim(0, 23)


def _zone_lines(ax: Any, table: pd.DataFrame, x: Any, *, scale: float = 1.0, **kw: Any) -> None:
    for zone in table.columns:
        ax.plot(
            x,
            table[zone] * scale,
            color=ZONE_COLORS.get(str(zone), TEXT_2),
            label=_label(str(zone)),
            **kw,
        )


def zone_month_heatmap(
    table: pd.DataFrame, title: str, subtitle: str, unit: str, *, scale: float = 1.0
) -> Any:
    """Rows = zones, columns = months; one sequential hue, darker = higher."""
    data = table.T * scale
    fig, (ax,) = new_figure(title, subtitle, height=4.2)
    im = ax.imshow(data.to_numpy(), aspect="auto", cmap=SEQ_CMAP, interpolation="nearest")
    ax.set_yticks(range(len(data.index)), [_label(str(z)) for z in data.index])
    months = pd.DatetimeIndex(table.index)
    ticks = [i for i, m in enumerate(months) if m.month in (1, 7)] or [0]
    ax.set_xticks(ticks, [f"{months[i]:%b %Y}" for i in ticks])
    ax.grid(False)
    ax.tick_params(length=0)
    # thin surface lines between cells
    ax.set_xticks(np.arange(-0.5, len(months), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(data.index), 1), minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=1.5)
    ax.tick_params(which="minor", length=0)
    cb = fig.colorbar(im, ax=ax, pad=0.02)
    cb.set_label(unit, color=TEXT_2)
    cb.outline.set_visible(False)
    ax.set_xlabel("month (Europe/Paris)")
    layout(fig, top=0.8)
    fig.subplots_adjust(left=LEFT_LABELS, right=0.98)
    return fig


def price_heatmap(monthly: pd.DataFrame) -> Any:
    return zone_month_heatmap(
        monthly,
        "Monthly mean day-ahead price by bidding zone",
        f"EUR/MWh, mean over all market time units of the month, {_period(monthly.index)}",
        "EUR/MWh",
    )


def negative_heatmap(monthly: pd.DataFrame) -> Any:
    return zone_month_heatmap(
        monthly,
        "Share of time with a negative day-ahead price",
        f"% of the month's market time units below 0 EUR/MWh, {_period(monthly.index)}",
        "% of time",
        scale=100,
    )


def spread_distribution(dist: pd.DataFrame, period: str) -> Any:
    """Per neighbour: P5-P95 (thin), P25-P75 (thick) and the median of the spread to France."""
    fig, (ax,) = new_figure(
        "Price spread to France: distribution",
        f"Neighbour price - French price, EUR/MWh, {period}. Thin: 5th-95th percentile; "
        "thick: 25th-75th; dot: median.",
        height=4.4,
    )
    y = np.arange(len(dist))
    for i, (zone, row) in enumerate(dist.iterrows()):
        color = ZONE_COLORS.get(str(zone), TEXT_2)
        ax.plot([row["p05"], row["p95"]], [i, i], color=color, linewidth=2, solid_capstyle="round")
        ax.plot([row["p25"], row["p75"]], [i, i], color=color, linewidth=9, solid_capstyle="round")
        ax.plot(row["median"], i, "o", color=TEXT, markersize=8, markeredgecolor=SURFACE, mew=2)
        ax.annotate(
            f"median {row['median']:+.1f}",
            xy=(row["p95"], i),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=TEXT,
        )
    ax.set_yticks(y, [_label(str(z)) for z in dist.index])
    ax.invert_yaxis()
    ax.axvline(0, color=TEXT_2, linewidth=0.8)
    ax.set_xlabel("EUR/MWh (positive = neighbour more expensive than France)")
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    layout(fig, top=0.8)
    fig.subplots_adjust(left=LEFT_LABELS)
    return fig


def spread_by_hour(table: pd.DataFrame, period: str) -> Any:
    fig, (ax,) = new_figure(
        "Price spread to France by hour of day",
        f"Mean of neighbour price - French price, EUR/MWh, per local hour, {period}",
    )
    _zone_lines(ax, table, table.index)
    ax.axhline(0, color=TEXT_2, linewidth=0.8)
    _hour_axis(ax)
    ax.set_ylabel("EUR/MWh")
    ax.legend(ncol=5, loc="upper left", bbox_to_anchor=(0, 1.1))
    return layout(fig, top=0.8)


def spread_by_month(table: pd.DataFrame) -> Any:
    fig, (ax,) = new_figure(
        "Price spread to France by month",
        f"Mean of neighbour price - French price, EUR/MWh, {_period(table.index)}",
    )
    x = pd.DatetimeIndex(table.index)
    _zone_lines(ax, table, x, marker="o", markersize=4)
    ax.axhline(0, color=TEXT_2, linewidth=0.8)
    if len(x) > 1:
        ax.set_xlim(x[0], x[-1])
    ax.set_ylabel("EUR/MWh")
    ax.legend(ncol=5, loc="upper left", bbox_to_anchor=(0, 1.1))
    return layout(fig, top=0.8)


def convergence_by_month(table: pd.DataFrame) -> Any:
    fig, (ax,) = new_figure(
        "Price convergence with France",
        "% of time the neighbour's day-ahead price equals France's (to the cent), monthly, "
        + _period(table.index),
    )
    x = pd.DatetimeIndex(table.index)
    zones = table.drop(columns="all_zones", errors="ignore")
    _zone_lines(ax, zones, x, scale=100, marker="o", markersize=4)
    if "all_zones" in table:
        ax.plot(x, table["all_zones"] * 100, color=TEXT_2, linestyle="--", label="All six zones")
    if len(x) > 1:
        ax.set_xlim(x[0], x[-1])
    ax.set_ylim(bottom=0)
    ax.set_ylabel("% of time")
    ax.legend(ncol=6, loc="upper left", bbox_to_anchor=(0, 1.1), fontsize=9)
    return layout(fig, top=0.8)


def flow_vs_spread(table: pd.DataFrame, period: str) -> Any:
    """100% bars per border: physical flow with / against the price spread, or no flow."""
    fig, (ax,) = new_figure(
        "Does power flow from the cheap to the expensive zone?",
        f"Physical net flow on each French border when prices differ, {period}",
        height=4.0,
    )
    parts = [
        ("with_spread", "Cheap to expensive", SERIES[0]),
        ("against_spread", "Expensive to cheap", SERIES[1]),
        ("no_flow", "No flow (< 50 MW)", GRID),
    ]
    y = np.arange(len(table))
    left = np.zeros(len(table))
    for col, name, color in parts:
        v = table[col].to_numpy() * 100
        ax.barh(y, v, left=left, color=color, label=name, edgecolor=SURFACE, linewidth=2)
        for i, (lo, w) in enumerate(zip(left, v, strict=True)):
            if w >= 6:
                ax.text(lo + w / 2, i, f"{w:.0f}%", ha="center", va="center", fontsize=9,
                        color=SURFACE if col != "no_flow" else TEXT)  # fmt: skip
        left += v
    ax.set_yticks(y, [_label(str(z)) for z in table.index])
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("% of quarter-hours with different prices")
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    ax.set_axisbelow(True)
    ax.legend(ncol=3, loc="upper left", bbox_to_anchor=(0, 1.14))
    layout(fig, top=0.78)
    fig.subplots_adjust(left=LEFT_LABELS)
    return fig


def against_by_spread_size(table: pd.DataFrame, period: str) -> Any:
    fig, (ax,) = new_figure(
        "Flows against the spread happen when the spread is small",
        f"% of decoupled quarter-hours with the physical flow from the expensive to the cheap "
        f"zone, by size of the spread, {period}",
    )
    x = np.arange(len(table))
    _zone_lines(ax, table, x, scale=100, marker="o", markersize=6)
    ax.set_xticks(x, [str(i) for i in table.index])
    ax.set_xlabel("|spread|, EUR/MWh")
    ax.set_ylabel("% of quarter-hours")
    ax.set_ylim(bottom=0)
    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0, 1.1))
    return layout(fig, top=0.8)


def negative_vs_solar(neg_by_hour: pd.DataFrame, solar: pd.DataFrame, period: str) -> Any:
    """Two panels on the same hour axis: relative solar output and the share of negative prices."""
    fig, (ax1, ax2) = new_figure(
        "Negative prices line up with solar output",
        f"By local hour, {period}. Top: solar, % of yearly peak (NL left out: incomplete data). "
        "Bottom: % of time negative.",
        nrows=2,
        height=6.2,
    )
    _zone_lines(ax1, solar, solar.index, scale=100)
    ax1.set_ylabel("solar, % of yearly peak")
    ax1.set_ylim(bottom=0)
    _zone_lines(ax2, neg_by_hour, neg_by_hour.index, scale=100)
    ax2.set_ylabel("% of time negative")
    ax2.set_ylim(bottom=0)
    _hour_axis(ax2)
    handles, labels = ax2.get_legend_handles_labels()
    ax1.legend(handles, labels, ncol=6, loc="upper left", bbox_to_anchor=(0, 1.25), fontsize=9)
    fig.subplots_adjust(hspace=0.2)
    return layout(fig, top=0.8)


def congestion_by_month(table: pd.DataFrame) -> Any:
    """One panel per NTC border: share of time the day-ahead exchange uses the whole NTC."""
    borders = sorted({str(c).rsplit("_", 1)[0] for c in table.columns})
    fig, axes = new_figure(
        "Congestion on France's NTC borders",
        "% of time the day-ahead commercial exchange uses the whole day-ahead NTC, by direction, "
        + _period(table.index),
        nrows=len(borders),
        height=2.6 + 2.0 * len(borders),
    )
    x = pd.DatetimeIndex(table.index)
    for ax, border in zip(axes, borders, strict=True):
        ax.plot(x, table[f"{border}_export"] * 100, color=SERIES[0], marker="o", markersize=4,
                label="France exporting at the limit")  # fmt: skip
        ax.plot(x, table[f"{border}_import"] * 100, color=SERIES[1], marker="o", markersize=4,
                label="France importing at the limit")  # fmt: skip
        ax.set_ylim(0, 100)
        ax.set_ylabel(f"{_label(border)}, %")
    if len(x) > 1:
        axes[-1].set_xlim(x[0], x[-1])
    axes[0].legend(ncol=2, loc="upper left", bbox_to_anchor=(0, 1.3))
    fig.subplots_adjust(hspace=0.3)
    return layout(fig, top=0.8)
