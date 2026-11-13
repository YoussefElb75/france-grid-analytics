"""README charts and result tables for the European analysis (aggregates only).

Built from the locally downloaded ``eu_prices``, ``flows``, ``eu_solar`` and ``eu_capacity``
datasets, restricted to complete calendar months that all of them cover.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from frgrid import europe as eu
from frgrid import europe_figures as ef
from frgrid.areas import LOCAL_TZ, ZONE_LABELS
from frgrid.style import save_figure


@dataclass(frozen=True)
class EuropeInputs:
    prices: pd.DataFrame
    flows: pd.DataFrame
    solar: pd.DataFrame
    capacity: pd.DataFrame | None


def complete_months_end(*frames: pd.DataFrame) -> pd.Timestamp:
    """UTC start of the month after the last calendar month fully covered by every frame."""
    ends = []
    for frame in frames:
        last = pd.DatetimeIndex(frame.dropna(how="all").index).max().tz_convert(LOCAL_TZ)
        month_end = last.normalize().replace(day=1) + pd.offsets.MonthBegin(1)
        complete = last + pd.Timedelta(minutes=15) >= month_end
        ends.append(month_end if complete else last.normalize().replace(day=1))
    return min(ends).tz_convert("UTC")


def trim(inp: EuropeInputs) -> EuropeInputs:
    """Keep the complete months common to prices, flows and solar."""
    end = complete_months_end(inp.prices, inp.flows, inp.solar)

    def cut(frame: pd.DataFrame) -> pd.DataFrame:
        return frame[frame.index < end]

    cap = None if inp.capacity is None else cut(inp.capacity)
    return EuropeInputs(cut(inp.prices), cut(inp.flows), cut(inp.solar), cap)


def period_of(prices: pd.DataFrame) -> str:
    idx = pd.DatetimeIndex(prices.dropna(how="all").index).tz_convert(LOCAL_TZ)
    return f"{idx.min():%b %Y} - {idx.max():%b %Y}"


def _pct(x: Any) -> str:
    v = float(x)
    return f"{v:.0%}" if v >= 0.1 or v == 0 else f"{v:.1%}"


def _day(ts: Any) -> str:
    return "-" if pd.isna(ts) else f"{pd.Timestamp(ts):%Y-%m-%d}"


def _zone(z: object) -> str:
    return ZONE_LABELS.get(str(z), str(z))


def results_markdown(inp: EuropeInputs) -> str:
    p, period = inp.prices, period_of(inp.prices)
    years = pd.Index(pd.DatetimeIndex(p.index).tz_convert(LOCAL_TZ).year, name="year")
    yearly = p[eu.zones(p)].groupby(years).mean()
    spr = eu.spreads(p)
    dist = eu.spread_distribution(spr)
    conv = eu.convergence_summary(p)
    allz = float(eu.all_converged(p).mean())
    fvs = eu.flow_vs_spread(p, inp.flows)
    bysize = eu.against_by_spread_size(p, inp.flows)
    neg_year = eu.negative_by_year(p)
    neg = eu.negative_solar_summary(p, inp.solar)
    res = eu.resolution_periods(p)
    last_year = int(years.max())
    last_months = pd.DatetimeIndex(p.index).tz_convert(LOCAL_TZ)
    partial = f"{last_year} (Jan-{last_months.max():%b})" if last_months.max().month < 12 else ""

    lines = [f"Period: {period}, {len(p):,} quarter-hours per zone.", ""]
    lines += ["**Mean day-ahead price, EUR/MWh**", ""]
    head = [str(y) if y != last_year or not partial else partial for y in yearly.index]
    lines += ["| Zone | " + " | ".join(head) + " |", "|---|" + "---:|" * len(head)]
    for col in yearly.columns:
        lines.append(f"| {_zone(col)} | " + " | ".join(f"{v:.1f}" for v in yearly[col]) + " |")

    lines += ["", "**Spread to France and convergence** (spread = neighbour - France)", ""]
    lines += [
        "| Neighbour | mean spread | median | P5 / P95 | equal prices | within 1 EUR | "
        "France cheaper | France dearer |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for z, r in dist.iterrows():
        c = conv.loc[str(z)]
        lines.append(
            f"| {_zone(z)} | {r['mean']:+.1f} | {r['median']:+.1f} | "
            f"{r['p05']:+.0f} / {r['p95']:+.0f} | {_pct(c['converged'])} | "
            f"{_pct(c['within_1_eur'])} | {_pct(c['fr_cheaper'])} | {_pct(c['fr_dearer'])} |"
        )
    lines += ["", f"All six zones at the same price: {allz:.1%} of the time.", ""]

    lines += ["**Physical flow vs the spread** (quarter-hours with different prices)", ""]
    lines += [
        "| Border | cheap to expensive | expensive to cheap | against, spread up to 1 EUR | "
        "against, spread 20-50 EUR |",
        "|---|---:|---:|---:|---:|",
    ]
    for z, r in fvs.iterrows():
        lines.append(
            f"| {_zone(z)} | {_pct(r['with_spread'])} | {_pct(r['against_spread'])} | "
            f"{_pct(bysize.loc['0-1', str(z)])} | {_pct(bysize.loc['20-50', str(z)])} |"
        )

    if inp.capacity is not None:
        check = eu.congestion_check(p, inp.capacity)
        cong = eu.congestion_by_month(inp.capacity).mean()
        lines += ["", "**Congestion on the NTC borders** (day-ahead schedule vs day-ahead NTC)", ""]
        lines += [
            "| Border | France exporting at the limit | France importing at the limit | "
            "border full when prices differ | border full when prices are equal |",
            "|---|---:|---:|---:|---:|",
        ]
        for z, r in check.iterrows():
            lines.append(
                f"| {_zone(z)} | {_pct(cong[f'{z}_export'])} | {_pct(cong[f'{z}_import'])} | "
                f"{r['saturated_when_decoupled']:.1%} | {r['saturated_when_converged']:.1%} |"
            )

    lines += ["", "**Negative prices**", ""]
    yhead = [str(y) if y != last_year or not partial else partial for y in neg_year.index]
    lines += [
        "| Zone | " + " | ".join(f"hours {h}" for h in yhead) + " | 10:00-17:00 | weekends "
        "| March-May | solar >= half of yearly peak |",
        "|---|" + "---:|" * (len(yhead) + 4),
    ]
    for z, r in neg.iterrows():
        hours = " | ".join(f"{v:.0f}" for v in neg_year[z])
        cells = [r["in_daylight"], r["on_weekends"], r["in_spring"], r["solar_above_half"]]
        lines.append(
            f"| {_zone(z)} | {hours} | "
            + " | ".join("-" if pd.isna(v) else _pct(float(v)) for v in cells)
            + " |"
        )

    lines += ["", "**Published resolution of the day-ahead price**", ""]
    lines += ["| Zone | last hourly day | first PT15M day | PT15M days with hourly values |"]
    lines += ["|---|---|---|---:|"]
    for z, r in res.iterrows():
        lines.append(
            f"| {_zone(z)} | {_day(r['last_60'])} | {_day(r['first_15'])} | "
            f"{r['hourly_values_on_15min_days']} |"
        )
    return "\n".join(lines)


def build(inp: EuropeInputs, out_dir: Path) -> tuple[list[Path], str]:
    inp = trim(inp)
    p, period = inp.prices, period_of(inp.prices)
    spr = eu.spreads(p)
    figures = {
        "eu_price_heatmap.png": ef.price_heatmap(eu.monthly_mean_prices(p)),
        "eu_spread_by_hour.png": ef.spread_by_hour(eu.spread_by_hour(spr), period),
        "eu_flow_vs_spread.png": ef.flow_vs_spread(eu.flow_vs_spread(p, inp.flows), period),
        "eu_negative_solar.png": ef.negative_vs_solar(
            eu.negative_by_hour(p), eu.solar_profile(inp.solar), period
        ),
    }
    # the builders set their own margins (wider on charts with zone names on the y axis)
    paths = [save_figure(fig, out_dir / name, adjust=False) for name, fig in figures.items()]
    return paths, results_markdown(inp)
