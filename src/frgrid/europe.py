"""European day-ahead markets around France: spreads, convergence, flows and negative prices.

Inputs are the 15-minute UTC frames of :mod:`frgrid.datasets` (``eu_prices``, ``flows``,
``eu_solar``). Everything is computed on the 15-minute grid, so each quarter-hour weighs the
same: before 1 October 2025 an hourly price is repeated four times, which makes "share of time"
identical to "share of hours"; from then on it is the share of 15-minute market time units.

Definitions (also documented in the README)
-------------------------------------------
* **Spread** to France = price of the neighbouring zone - price of France, EUR/MWh. Positive
  means the neighbour is more expensive.
* **Convergence**: the two prices are equal to the cent (``|spread| < 0.005``). In market
  coupling, equal prices mean no network constraint between the two zones was binding (no
  congestion); different prices mean one was. In the flow-based Core region (FR, BE, NL, DE-LU)
  that constraint need not be on the common border.
* **Flow against the spread**: a quarter-hour with different prices where the *physical* net flow
  on the border goes from the expensive zone to the cheap one. Flows below
  :data:`FLOW_DEADBAND_MW` count as no flow.
* **Saturated border** (NTC borders FR-ES and FR-IT-North only): the net day-ahead commercial
  exchange in one direction is within :data:`SATURATION_MW` of the day-ahead NTC.
* **Negative price**: strictly below 0 EUR/MWh.
* **Relative solar output**: solar generation divided by that zone's 99th percentile of solar
  generation in the same calendar year, capped at 1. It makes zones of very different size
  comparable and follows the growth of installed capacity from one year to the next, while
  keeping the seasons (a winter noon stays well below 1). Because capacity also grows *within*
  a year, high relative values cluster in late summer; the analysis therefore compares negative
  prices with solar by hour of day rather than by solar level.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

from frgrid.areas import FLOW_BORDER, LOCAL_TZ, PRICE_ZONES

CONVERGENCE_TOL: Final = 0.005
NEAR_TOL: Final = 1.0  # EUR/MWh, "near convergence"
FLOW_DEADBAND_MW: Final = 50.0
SATURATION_MW: Final = 1.0
SPREAD_BINS: Final = (0.0, 1.0, 5.0, 20.0, 50.0, np.inf)
SPREAD_BIN_LABELS: Final = ("0-1", "1-5", "5-20", "20-50", ">50")
DAYLIGHT_HOURS: Final = range(10, 17)  # local 10:00-16:59, the core of solar output
INCOMPLETE_SOLAR: Final = frozenset({"NL"})
"""Zones whose ENTSO-E solar series covers only a small part of the installed PV (NL peaks at
about 0.3 GW); they are left out of every solar comparison."""


def zones(frame: pd.DataFrame) -> list[str]:
    """Zone price columns present in an ``eu_prices`` frame, in :data:`PRICE_ZONES` order."""
    return [z for z in PRICE_ZONES if z in frame.columns]


def neighbours(frame: pd.DataFrame) -> list[str]:
    return [z for z in zones(frame) if z != "FR"]


def _local(index: pd.Index[pd.Timestamp]) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(index).tz_convert(LOCAL_TZ)


def _months(index: pd.Index[pd.Timestamp]) -> pd.DatetimeIndex:
    """Naive Europe/Paris month start of each timestamp."""
    return _local(index).tz_localize(None).to_period("M").to_timestamp().rename("month")


def _hours(index: pd.Index[pd.Timestamp]) -> pd.Index[int]:
    return pd.Index(_local(index).hour, name="hour")


# ---- prices and resolution ---------------------------------------------------------------------


def monthly_mean_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Monthly mean day-ahead price per zone (rows: naive month starts), EUR/MWh."""
    z = zones(prices)
    return prices[z].groupby(_months(prices.index)).mean()


def resolution_periods(prices: pd.DataFrame) -> pd.DataFrame:
    """Per zone: when the published resolution was 60 and 15 minutes (Europe/Paris days).

    Also counts the days published on a 15-minute grid whose four quarter-hours all carry the
    same price (``hourly_values_on_15min_days``): an hourly price in a 15-minute format.
    """
    rows = {}
    for z in zones(prices):
        res = prices[f"res_{z}"].dropna()
        p = prices[z]
        days = _local(res.index).tz_localize(None).normalize()
        per_day = res.groupby(days).min()
        q = p[prices[f"res_{z}"] == 15.0].dropna()
        q_days = _local(q.index).tz_localize(None).normalize()
        hours = _local(q.index).tz_localize(None).floor("h")
        flat_hour = q.groupby(hours).nunique() == 1
        flat_day = flat_hour.groupby(pd.DatetimeIndex(flat_hour.index).normalize()).all()
        rows[z] = {
            "first_60": per_day[per_day == 60].index.min(),
            "last_60": per_day[per_day == 60].index.max(),
            "first_15": per_day[per_day == 15].index.min(),
            "days_15": int((per_day == 15).sum()),
            "hourly_values_on_15min_days": int(flat_day.reindex(q_days.unique()).sum()),
        }
    return pd.DataFrame.from_dict(rows, orient="index")


# ---- spreads and convergence -------------------------------------------------------------------


def spreads(prices: pd.DataFrame) -> pd.DataFrame:
    """Neighbour price - French price, EUR/MWh, one column per neighbouring zone."""
    return pd.DataFrame({z: prices[z] - prices["FR"] for z in neighbours(prices)})


def converged(prices: pd.DataFrame, tol: float = CONVERGENCE_TOL) -> pd.DataFrame:
    """1.0 where the zone's price equals France's, 0.0 where it differs, NaN if one is missing."""
    s = spreads(prices)
    return (s.abs() < tol).astype(float).where(s.notna())


def all_converged(prices: pd.DataFrame, tol: float = CONVERGENCE_TOL) -> pd.Series[float]:
    """1.0 where all zones have the same price (no congestion anywhere between them)."""
    z = zones(prices)
    p = prices[z]
    out = ((p.max(axis=1) - p.min(axis=1)) < tol).astype(float)
    return out.where(p.notna().all(axis=1)).rename("all_zones")


def spread_distribution(spr: pd.DataFrame) -> pd.DataFrame:
    """Per neighbour: mean, mean absolute value and percentiles of the spread, EUR/MWh."""
    q = spr.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).T
    q.columns = pd.Index(["p05", "p25", "median", "p75", "p95"])
    q.insert(0, "mean", spr.mean())
    q.insert(1, "mean_abs", spr.abs().mean())
    q.index.name = "zone"
    return q


def spread_by_hour(spr: pd.DataFrame, stat: str = "mean") -> pd.DataFrame:
    """Spread per local hour of day (rows 0-23) and neighbour; ``stat`` is mean or median."""
    return spr.groupby(_hours(spr.index)).agg(stat)


def spread_by_month(spr: pd.DataFrame) -> pd.DataFrame:
    """Monthly mean spread per neighbour (rows: naive month starts)."""
    return spr.groupby(_months(spr.index)).mean()


def convergence_by_month(prices: pd.DataFrame) -> pd.DataFrame:
    """Share of time each neighbour's price equals France's, per month, plus ``all_zones``."""
    conv = converged(prices)
    conv["all_zones"] = all_converged(prices)
    return conv.groupby(_months(conv.index)).mean()


def convergence_by_hour(prices: pd.DataFrame) -> pd.DataFrame:
    conv = converged(prices)
    return conv.groupby(_hours(conv.index)).mean()


def convergence_summary(prices: pd.DataFrame) -> pd.DataFrame:
    """Per neighbour over the whole frame: share of time converged, FR cheaper, FR dearer.

    ``within_1_eur`` is the share with ``|spread| < 1`` EUR/MWh: flow-based coupling often
    leaves prices a few cents apart, which is congestion but economically small.
    """
    spr = spreads(prices)
    valid = spr.notna()
    n = valid.sum()
    out = pd.DataFrame(
        {
            "converged": (spr.abs() < CONVERGENCE_TOL).sum() / n,
            "fr_cheaper": (spr >= CONVERGENCE_TOL).sum() / n,
            "fr_dearer": (spr <= -CONVERGENCE_TOL).sum() / n,
            "within_1_eur": (spr.abs() < NEAR_TOL).sum() / n,
            "quarter_hours": n,
        }
    )
    out.index.name = "zone"
    return out


# ---- spreads vs physical flows -----------------------------------------------------------------


def net_exports(flows: pd.DataFrame) -> pd.DataFrame:
    """Net physical flow out of France per price zone with a border, MW (export - import)."""
    cols = {}
    for zone, border in FLOW_BORDER.items():
        if f"export_{border}" in flows and f"import_{border}" in flows:
            cols[zone] = flows[f"export_{border}"] - flows[f"import_{border}"]
    return pd.DataFrame(cols, index=flows.index)


def flow_direction(prices: pd.DataFrame, flows: pd.DataFrame) -> pd.DataFrame:
    """Per quarter-hour and border: +1 flow with the spread (cheap -> dear), -1 against, 0 none.

    NaN where prices converge (no direction is implied) or where data are missing.
    """
    spr = spreads(prices)
    net = net_exports(flows).reindex(spr.index)
    out = {}
    for zone in net.columns:
        s, f = spr[zone], net[zone]
        flow_sign = np.sign(f).where(f.abs() >= FLOW_DEADBAND_MW, 0.0)
        # FR exports (f > 0) follow the spread when the neighbour is dearer (s > 0).
        d = flow_sign * np.sign(s)
        out[zone] = d.where(s.abs() >= CONVERGENCE_TOL).where(s.notna() & f.notna())
    return pd.DataFrame(out, index=spr.index)


def flow_vs_spread(prices: pd.DataFrame, flows: pd.DataFrame) -> pd.DataFrame:
    """Per border, over the quarter-hours with different prices: how the physical flow went.

    Columns: ``with_spread`` (cheap -> dear), ``against_spread``, ``no_flow`` (shares), the number
    of decoupled quarter-hours, and the mean |spread| and |flow| when the flow went against it.
    """
    d = flow_direction(prices, flows)
    spr = spreads(prices)
    net = net_exports(flows).reindex(spr.index)
    rows = {}
    for zone in d.columns:
        x = d[zone].dropna()
        against = x.index[x < 0]
        rows[zone] = {
            "with_spread": float((x > 0).mean()),
            "against_spread": float((x < 0).mean()),
            "no_flow": float((x == 0).mean()),
            "decoupled_quarter_hours": len(x),
            "mean_abs_spread_against": float(spr.loc[against, zone].abs().mean()),
            "mean_abs_flow_against_mw": float(net.loc[against, zone].abs().mean()),
        }
    out = pd.DataFrame.from_dict(rows, orient="index")
    out.index.name = "zone"
    return out


def against_by_spread_size(prices: pd.DataFrame, flows: pd.DataFrame) -> pd.DataFrame:
    """Share of decoupled quarter-hours with the flow against the spread, by |spread| bin."""
    d = flow_direction(prices, flows)
    spr = spreads(prices).abs()
    out = {}
    for zone in d.columns:
        x = d[zone].dropna()
        bins = pd.cut(spr.loc[x.index, zone], SPREAD_BINS, labels=list(SPREAD_BIN_LABELS))
        out[zone] = (x < 0).astype(float).groupby(bins, observed=False).mean()
    table = pd.DataFrame(out)
    table.index.name = "abs_spread_eur_mwh"
    return table


# ---- congestion on the NTC borders ------------------------------------------------------------


def capacity_borders(capacity: pd.DataFrame) -> list[str]:
    return [z for z in PRICE_ZONES if f"ntc_FR_to_{z}" in capacity.columns]


def saturation(capacity: pd.DataFrame) -> pd.DataFrame:
    """Per NTC border and quarter-hour: +1 if the day-ahead exchange France -> neighbour uses the
    whole NTC, -1 if neighbour -> France does, 0 otherwise; NaN where data are missing.

    "Uses the whole NTC" means the net day-ahead schedule in that direction is within
    :data:`SATURATION_MW` of the NTC (or above it) and the NTC is positive.
    """
    out = {}
    for z in capacity_borders(capacity):
        net = capacity[f"da_FR_to_{z}"] - capacity[f"da_{z}_to_FR"]
        ntc_out, ntc_in = capacity[f"ntc_FR_to_{z}"], capacity[f"ntc_{z}_to_FR"]
        export_full = (ntc_out > 0) & (net >= ntc_out - SATURATION_MW)
        import_full = (ntc_in > 0) & (-net >= ntc_in - SATURATION_MW)
        value = pd.Series(0.0, index=capacity.index).mask(export_full, 1.0).mask(import_full, -1.0)
        valid = net.notna() & ntc_out.notna() & ntc_in.notna()
        out[z] = value.where(valid)
    return pd.DataFrame(out, index=capacity.index)


def congestion_by_month(capacity: pd.DataFrame) -> pd.DataFrame:
    """Share of time each NTC border is saturated, per month, in each direction.

    Columns ``<zone>_export`` (France -> neighbour full) and ``<zone>_import``.
    """
    sat = saturation(capacity)
    cols = {}
    for z in sat.columns:
        cols[f"{z}_export"] = (sat[z] == 1.0).astype(float).where(sat[z].notna())
        cols[f"{z}_import"] = (sat[z] == -1.0).astype(float).where(sat[z].notna())
    frame = pd.DataFrame(cols, index=sat.index)
    return frame.groupby(_months(frame.index)).mean()


def ntc_by_month(capacity: pd.DataFrame) -> pd.DataFrame:
    """Monthly mean day-ahead NTC per border and direction, MW."""
    cols = [c for c in capacity.columns if str(c).startswith("ntc_")]
    return capacity[cols].groupby(_months(capacity.index)).mean()


def congestion_check(prices: pd.DataFrame, capacity: pd.DataFrame) -> pd.DataFrame:
    """How well the published NTC explains the prices, per NTC border.

    * ``saturated_when_decoupled``: among quarter-hours with different prices, the share where
      the day-ahead exchange uses the whole NTC from the cheap to the expensive zone (should be
      close to 1 if the NTC is the capacity the market actually used);
    * ``saturated_when_converged``: among quarter-hours with equal prices, the share with a
      saturated border (should be close to 0);
    * ``saturated``: share of all quarter-hours with the border saturated in either direction.
    """
    sat = saturation(capacity)
    spr = spreads(prices).reindex(sat.index)
    rows = {}
    for z in sat.columns:
        frame = pd.DataFrame({"sat": sat[z], "s": spr[z]}).dropna()
        dec = frame[frame["s"].abs() >= CONVERGENCE_TOL]
        conv = frame[frame["s"].abs() < CONVERGENCE_TOL]
        right_way = np.sign(dec["s"]) == dec["sat"]
        rows[z] = {
            "saturated_when_decoupled": float(right_way.mean()),
            "saturated_when_converged": float((conv["sat"] != 0).mean()),
            "saturated": float((frame["sat"] != 0).mean()),
            "quarter_hours": len(frame),
        }
    out = pd.DataFrame.from_dict(rows, orient="index")
    out.index.name = "zone"
    return out


# ---- negative prices and solar -----------------------------------------------------------------


def negative(prices: pd.DataFrame) -> pd.DataFrame:
    """1.0 where a zone's price is below zero, 0.0 otherwise, NaN where missing."""
    p = prices[zones(prices)]
    return (p < 0).astype(float).where(p.notna())


def negative_by_month(prices: pd.DataFrame) -> pd.DataFrame:
    """Share of time with a negative price, per zone and month."""
    neg = negative(prices)
    return neg.groupby(_months(neg.index)).mean()


def negative_by_year(prices: pd.DataFrame) -> pd.DataFrame:
    """Equivalent hours with a negative price per zone and calendar year (quarter-hours / 4)."""
    neg = negative(prices)
    years = pd.Index(_local(neg.index).year, name="year")
    return neg.groupby(years).sum() / 4


def negative_by_hour(prices: pd.DataFrame) -> pd.DataFrame:
    """Share of time with a negative price per local hour of day (rows) and zone."""
    neg = negative(prices)
    return neg.groupby(_hours(neg.index)).mean()


def solar_zones(solar: pd.DataFrame) -> list[str]:
    """Zones whose solar series is usable (see :data:`INCOMPLETE_SOLAR`)."""
    return [z for z in zones(solar) if z not in INCOMPLETE_SOLAR]


def relative_solar(solar: pd.DataFrame) -> pd.DataFrame:
    """Solar output over the zone's 99th percentile in the same calendar year, in [0, 1]."""
    z = solar_zones(solar)
    years = pd.Index(_local(solar.index).year, name="year")
    peak = solar[z].groupby(years).transform(lambda s: s.quantile(0.99))
    rel = solar[z] / peak.where(peak > 0)
    return rel.clip(0, 1)


def solar_profile(solar: pd.DataFrame) -> pd.DataFrame:
    """Mean relative solar output per local hour of day (rows) and zone."""
    rel = relative_solar(solar)
    return rel.groupby(_hours(rel.index)).mean()


def negative_solar_summary(prices: pd.DataFrame, solar: pd.DataFrame) -> pd.DataFrame:
    """Per zone: negative-price hours per year and when they happen.

    * ``negative_share``: share of time with a negative price;
    * ``hours_per_year``: equivalent hours per year (quarter-hours / 4, scaled to 365.25 days);
    * ``in_daylight``: share of negative quarter-hours between local 10:00 and 17:00;
    * ``on_weekends``: share on Saturdays and Sundays (2/7 = 29% if evenly spread);
    * ``in_spring``: share in March-May (25% of the year);
    * ``solar_above_half``: share with relative solar output >= 0.5 (NaN without usable solar);
    * ``corr_solar``: correlation of the price with relative solar output.
    """
    rel = relative_solar(solar).reindex(prices.index)
    neg = negative(prices)
    local = _local(prices.index)
    daylight = pd.Series(local.hour.isin(list(DAYLIGHT_HOURS)), index=prices.index)
    weekend = pd.Series(local.day_of_week >= 5, index=prices.index)
    spring = pd.Series(local.month.isin([3, 4, 5]), index=prices.index)
    rows = {}
    for z in zones(prices):
        n = neg[z]
        is_neg = n == 1.0
        any_neg = bool(is_neg.any())
        days = float(n.notna().sum()) / 96
        rows[z] = {
            "negative_share": float(n.mean()),
            "hours_per_year": float(n.sum() / 4 * 365.25 / days) if days else np.nan,
            "in_daylight": float(daylight[is_neg].mean()) if any_neg else np.nan,
            "on_weekends": float(weekend[is_neg].mean()) if any_neg else np.nan,
            "in_spring": float(spring[is_neg].mean()) if any_neg else np.nan,
            "solar_above_half": float((rel.loc[is_neg, z] >= 0.5).mean())
            if z in rel and any_neg
            else np.nan,
            "corr_solar": float(prices[z].corr(rel[z])) if z in rel else np.nan,
        }
    out = pd.DataFrame.from_dict(rows, orient="index")
    out.index.name = "zone"
    return out
