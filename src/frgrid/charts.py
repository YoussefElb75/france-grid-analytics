"""README charts and result tables, built from the locally downloaded data.

Charts show derived, aggregated statistics only (monthly means, average profiles, densities,
backtest errors) and each carries the source line required by the ENTSO-E Terms of Use.

Colours follow a validated categorical order (blue, orange, aqua, yellow, magenta, green) on a
light surface; series are also labelled directly or by legend, never by colour alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap

from frgrid import analytics as an
from frgrid.areas import LOCAL_TZ
from frgrid.forecast import Backtest, backtest

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
SEQUENTIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
SOURCE = "Source: ENTSO-E Transparency Platform; analysis: france-grid-analytics"

GENERATION_GROUPS: dict[str, list[str]] = {
    "Nuclear": ["Nuclear"],
    "Hydro": ["Hydro Run-of-river and poundage", "Hydro Water Reservoir"],
    "Wind": ["Wind Onshore", "Wind Offshore"],
    "Solar": ["Solar"],
    "Gas": ["Fossil Gas"],
    "Other": [
        "Biomass",
        "Waste",
        "Fossil Hard coal",
        "Fossil Oil",
        "Fossil Brown coal/Lignite",
        "Fossil Coal-derived gas",
        "Geothermal",
        "Marine",
        "Other renewable",
        "Other",
    ],
}

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


@dataclass(frozen=True)
class Inputs:
    prices: pd.DataFrame
    load: pd.DataFrame
    generation: pd.DataFrame
    flows: pd.DataFrame | None


def _figure(title: str, subtitle: str, nrows: int = 1, height: float = 4.8) -> tuple[Any, Any]:
    fig, axes = plt.subplots(nrows, 1, figsize=(9.6, height), sharex=nrows > 1, squeeze=False)
    fig.suptitle(title, x=0.012, y=0.975, ha="left", fontsize=13, fontweight="bold")
    fig.text(0.012, 0.975 - 0.33 / height, subtitle, ha="left", color=TEXT_2)
    fig.text(0.012, 0.012, SOURCE, ha="left", color=TEXT_2, fontsize=8)
    return fig, axes[:, 0]


def _save(fig: Any, path: Path, top: float = 0.82) -> Path:
    fig.subplots_adjust(left=0.08, right=0.86, top=top, bottom=0.14)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)
    return path


def _label_line_ends(ax: Any, frame: pd.DataFrame, fmt: str = "{name}") -> None:
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


def _period(index: pd.Index[Any]) -> str:
    idx = pd.DatetimeIndex(index).tz_convert(LOCAL_TZ)
    return f"{idx.min():%b %Y} - {idx.max():%b %Y}"


def price_profile(inp: Inputs, out: Path) -> Path:
    hourly = an.hourly(inp.prices)["price_eur_mwh"]
    prof = an.daily_profile(hourly, by="season")
    fig, (ax,) = _figure(
        "Average day-ahead price by hour of day, France",
        f"EUR/MWh, mean per local hour and season, {_period(hourly.index)}",
    )
    for i, col in enumerate(prof.columns):
        ax.plot(prof.index, prof[col], color=SERIES[i], label=str(col).capitalize())
    _label_line_ends(ax, prof.rename(columns=lambda c: str(c).capitalize()))
    ax.set_xticks(range(0, 24, 3), [f"{h:02d}:00" for h in range(0, 24, 3)])
    ax.set_xlim(0, 23)
    ax.set_ylabel("EUR/MWh")
    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0, 1.08))
    return _save(fig, out)


def _grouped_generation(generation: pd.DataFrame) -> pd.DataFrame:
    hourly = an.hourly(generation)
    keep = ~an.core_missing(hourly)
    groups = {
        name: hourly[[c for c in cols if c in hourly.columns]].sum(axis=1, min_count=1)
        for name, cols in GENERATION_GROUPS.items()
    }
    frame = pd.DataFrame(groups)[keep].fillna(0.0)
    return frame.tz_convert(LOCAL_TZ).resample("MS").mean() / 1e3


def generation_mix(inp: Inputs, out: Path) -> Path:
    monthly = _grouped_generation(inp.generation)
    fig, (ax,) = _figure(
        "Monthly generation mix, France",
        f"Average generation in GW by production type, {_period(monthly.index)}",
    )
    x = pd.DatetimeIndex(monthly.index).tz_localize(None)
    ax.stackplot(
        x,
        [monthly[c] for c in monthly.columns],
        colors=SERIES[: len(monthly.columns)],
        labels=list(monthly.columns),
        edgecolor=SURFACE,
        linewidth=1.0,
    )
    tops = monthly.cumsum(axis=1)
    mids = tops - monthly / 2
    for name in ("Nuclear", "Hydro", "Wind"):
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
    ax.set_xlim(x[0], x[-1])
    ax.legend(ncol=6, loc="upper left", bbox_to_anchor=(0, 1.1))
    return _save(fig, out, top=0.8)


def residual_load_price(inp: Inputs, out: Path) -> Path:
    hourly_rl = an.hourly(pd.DataFrame({"rl": an.residual_load(inp.load, inp.generation)}))["rl"]
    price = an.hourly(inp.prices)["price_eur_mwh"]
    frame = pd.concat({"rl": hourly_rl / 1e3, "p": price}, axis=1).dropna()
    clipped = frame[(frame["p"] > -150) & (frame["p"] < 350)]
    share = len(clipped) / len(frame)
    corr = float(frame["rl"].corr(frame["p"]))
    fig, (ax,) = _figure(
        "Price rises with load not covered by wind and solar",
        f"Hourly day-ahead price vs residual load (load - wind - solar), {_period(frame.index)}; "
        f"correlation {corr:.2f}, {share:.1%} of hours shown",
        height=5.2,
    )
    cmap = LinearSegmentedColormap.from_list("seq", SEQUENTIAL)
    hb = ax.hexbin(
        clipped["rl"], clipped["p"], gridsize=55, cmap=cmap, mincnt=1, bins="log", linewidths=0.2
    )
    cb = fig.colorbar(hb, ax=ax, pad=0.02)
    cb.set_label("hours (log scale)", color=TEXT_2)
    cb.outline.set_visible(False)
    ax.set_axisbelow(True)
    ax.set_xlabel("Residual load, GW")
    ax.set_ylabel("EUR/MWh")
    fig.subplots_adjust(right=0.98)
    return _save(fig, out, top=0.84)


def renewables_and_co2(inp: Inputs, out: Path) -> Path:
    hourly = an.hourly(inp.generation)
    monthly = (
        pd.DataFrame({"ren": an.renewable_share(hourly), "co2": an.co2_intensity(hourly)})
        .tz_convert(LOCAL_TZ)
        .resample("MS")
        .mean()
    )
    x = pd.DatetimeIndex(monthly.index).tz_localize(None)
    fig, (ax1, ax2) = _figure(
        "Renewable share and carbon intensity of French generation",
        f"Monthly means of hourly values, {_period(monthly.index)}",
        nrows=2,
        height=5.6,
    )
    ax1.plot(x, monthly["ren"] * 100, color=SERIES[0], marker="o", markersize=4)
    ax1.set_ylabel("renewable share, %")
    ax2.plot(x, monthly["co2"], color=SERIES[1], marker="o", markersize=4)
    ax2.set_ylabel("gCO2eq/kWh (life cycle)")
    for ax in (ax1, ax2):
        ax.set_ylim(bottom=0)
    fig.subplots_adjust(hspace=0.25)
    return _save(fig, out, top=0.86)


def net_exports(inp: Inputs, out: Path) -> Path | None:
    if inp.flows is None:
        return None
    net = -an.net_imports(an.hourly(inp.flows)).drop(columns="total")  # exports positive
    monthly = net.tz_convert(LOCAL_TZ).resample("MS").mean() / 1e3
    order = monthly.mean().sort_values(ascending=False).index
    monthly = monthly[order]
    fig, (ax,) = _figure(
        "France is a net exporter on most borders",
        "Net physical exports by border, monthly mean in GW (negative = net imports), "
        + _period(monthly.index),
    )
    x = np.arange(len(monthly))
    pos = np.zeros(len(monthly))
    neg = np.zeros(len(monthly))
    for i, border in enumerate(monthly.columns):
        v = monthly[border].fillna(0.0).to_numpy()
        bottom = np.where(v >= 0, pos, neg)
        ax.bar(
            x,
            v,
            bottom=bottom,
            width=0.78,
            color=SERIES[i],
            label=border,
            edgecolor=SURFACE,
            linewidth=0.8,
        )
        pos += np.where(v >= 0, v, 0)
        neg += np.where(v < 0, v, 0)
    ax.axhline(0, color=TEXT_2, linewidth=0.8)
    ticks = [i for i, d in enumerate(monthly.index) if d.month in (1, 7)]
    ax.set_xticks(ticks, [f"{monthly.index[i]:%b %Y}" for i in ticks])
    ax.set_ylabel("GW")
    ax.legend(title="border", loc="upper left", bbox_to_anchor=(1.01, 0.9))
    return _save(fig, out)


def forecast_errors(bt: Backtest, out: Path) -> Path:
    mae = bt.mae_by_month()
    mae.index = pd.PeriodIndex(mae.index).to_timestamp()
    names = {
        "model": "Ridge model",
        "naive_d1": "Naive: same hour D-1",
        "naive_d7": "Naive: same hour D-7",
    }
    fig, (ax,) = _figure(
        "Day-ahead price forecast vs naive baselines (walk-forward)",
        "Mean absolute error per month, EUR/MWh (lower is better)",
    )
    for i, col in enumerate(["model", "naive_d1", "naive_d7"]):
        ax.plot(mae.index, mae[col], color=SERIES[i], marker="o", markersize=4, label=names[col])
    _label_line_ends(ax, mae.rename(columns=names))
    ax.set_ylim(bottom=0)
    ax.set_ylabel("MAE, EUR/MWh")
    ax.legend(ncol=3, loc="upper left", bbox_to_anchor=(0, 1.08))
    return _save(fig, out)


def results_markdown(inp: Inputs, bt: Backtest) -> str:
    """Headline tables (aggregates only) for the README."""
    m = bt.metrics().round(1)
    by_year = bt.metrics_by_year().round(1)
    dm1 = bt.diebold_mariano("naive_d1")
    dm7 = bt.diebold_mariano("naive_d7")
    mae = bt.metrics().loc["MAE"].astype(float).to_dict()
    days = bt.predictions.index.get_level_values("day")
    lines = [
        f"Backtest: {days.nunique()} delivery days, {days.min():%d %b %Y} - {days.max():%d %b %Y}, "
        f"{len(bt.predictions):,} hourly forecasts.",
        "",
        "| | Ridge model | Naive D-1 | Naive D-7 |",
        "|---|---:|---:|---:|",
        *(
            "| {} (EUR/MWh) | {:.1f} | {:.1f} | {:.1f} |".format(k, *m.loc[k].astype(float))
            for k in ("MAE", "RMSE", "bias")
        ),
        *(
            f"| MAE {y} | {r['model']} | {r['naive_d1']} | {r['naive_d7']} |"
            for y, r in by_year.iterrows()
        ),
        "",
        f"MAE reduction vs naive D-1: {1 - mae['model'] / mae['naive_d1']:.0%}; vs naive D-7: "
        f"{1 - mae['model'] / mae['naive_d7']:.0%}. Diebold-Mariano (daily mean absolute error, "
        f"Newey-West, 7 lags): {dm1[0]:.1f} vs D-1, {dm7[0]:.1f} vs D-7 (p < 0.001 for both)"
        if max(dm1[1], dm7[1]) < 0.001
        else f"Diebold-Mariano: {dm1[0]:.2f} (p={dm1[1]:.3f}) vs D-1, "
        f"{dm7[0]:.2f} (p={dm7[1]:.3f}) vs D-7.",
    ]
    return "\n".join(lines)


def build(inp: Inputs, out_dir: Path) -> tuple[list[Path], str]:
    hourly_price = an.hourly(inp.prices)["price_eur_mwh"]
    hourly_load_fc = an.hourly(inp.load)["load_forecast_mw"]
    bt = backtest(hourly_price, hourly_load_fc)
    paths = [
        price_profile(inp, out_dir / "price_profile.png"),
        generation_mix(inp, out_dir / "generation_mix.png"),
        residual_load_price(inp, out_dir / "residual_load_price.png"),
        renewables_and_co2(inp, out_dir / "renewables_co2.png"),
        forecast_errors(bt, out_dir / "forecast_mae.png"),
    ]
    flows_chart = net_exports(inp, out_dir / "net_exports.png")
    if flows_chart is not None:
        paths.append(flows_chart)
    return paths, results_markdown(inp, bt)
