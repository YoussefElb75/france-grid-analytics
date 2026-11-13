"""Shared chart style for the README charts and the dashboard.

Colours follow a validated categorical order (blue, orange, aqua, yellow, magenta, green) on a
light surface; series are also labelled directly or by legend, never by colour alone. Every
figure carries the ENTSO-E source line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from frgrid.areas import LOCAL_TZ

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SOURCE = "Source: ENTSO-E Transparency Platform; analysis: france-grid-analytics"

plt.rcParams.update(
    {
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
        "font.size": 10,
        "text.color": TEXT,
        "axes.labelcolor": TEXT_2,
        "axes.edgecolor": GRID,
        "xtick.color": TEXT_2,
        "ytick.color": TEXT_2,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "legend.frameon": False,
        "lines.linewidth": 2.0,
    }
)


def new_figure(title: str, subtitle: str, nrows: int = 1, height: float = 4.8) -> tuple[Any, Any]:
    fig, axes = plt.subplots(nrows, 1, figsize=(9.6, height), sharex=nrows > 1, squeeze=False)
    fig.suptitle(title, x=0.012, y=0.975, ha="left", fontsize=13, fontweight="bold")
    fig.text(0.012, 0.975 - 0.33 / height, subtitle, ha="left", color=TEXT_2)
    fig.text(0.012, 0.012, SOURCE, ha="left", color=TEXT_2, fontsize=8)
    return fig, axes[:, 0]


def save_figure(fig: Any, path: Path, top: float = 0.82, *, adjust: bool = True) -> Path:
    """Save as PNG; ``adjust=False`` keeps margins the builder already set."""
    if adjust:
        fig.subplots_adjust(left=0.08, right=0.86, top=top, bottom=0.14)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)
    return path


def layout(fig: Any, top: float = 0.82) -> Any:
    """Apply the standard margins (for figures rendered by the dashboard instead of saved)."""
    fig.subplots_adjust(left=0.08, right=0.86, top=top, bottom=0.14)
    return fig


def label_line_ends(ax: Any, frame: pd.DataFrame, fmt: str = "{name}") -> None:
    """Direct labels at the right end of each line, nudged apart to avoid collisions."""
    last = frame.ffill().iloc[-1].dropna().sort_values()
    span = float(np.nanmax(frame.to_numpy()) - np.nanmin(frame.to_numpy())) or 1.0
    min_gap = 0.06 * span
    positions: list[float] = []
    for value in last.to_numpy():
        y = float(value) if not positions else max(float(value), positions[-1] + min_gap)
        positions.append(y)
    x = frame.index[-1]
    for (name, _), y in zip(last.items(), positions, strict=True):
        ax.annotate(
            fmt.format(name=name),
            xy=(x, y),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            color=TEXT,
            fontsize=9,
            annotation_clip=False,
        )


def period_label(index: pd.Index[Any]) -> str:
    idx = pd.DatetimeIndex(index).tz_convert(LOCAL_TZ)
    return f"{idx.min():%b %Y} - {idx.max():%b %Y}"


# Fixed colour per bidding zone, so a zone keeps its colour in every European chart.
ZONE_COLORS = {
    "DE_LU": SERIES[0],
    "BE": SERIES[1],
    "NL": SERIES[2],
    "ES": SERIES[3],
    "IT_NORTH": SERIES[4],
    "FR": SERIES[5],
}
