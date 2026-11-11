"""Descriptive analytics on the French power system.

All inputs are the 15-minute UTC frames from :mod:`frgrid.datasets`. Outputs are hourly averages
(MW, EUR/MWh) unless stated otherwise; profiles are expressed in Europe/Paris local time.

Definitions (also documented in the README)
-------------------------------------------
* **Generation** = sum of all production types, excluding storage output (pumped-storage
  turbining and "Energy storage"), which only re-releases energy produced earlier, and excluding
  every ``(consumption)`` column.
* **Renewable share** = (biomass + geothermal + run-of-river + reservoir hydro + marine + other
  renewable + solar + wind) / generation. Waste is excluded (only partly biogenic).
* **Residual load** = actual load - (solar + onshore wind + offshore wind).
* **CO2 intensity** = production-based, life-cycle gCO2eq/kWh of domestic generation, using the
  factors in :data:`EMISSION_FACTORS`. Imports are not included.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import pandas as pd

from frgrid.areas import LOCAL_TZ
from frgrid.codes import CONSUMPTION_SUFFIX

STORAGE: Final = frozenset({"Hydro Pumped Storage", "Energy storage"})
RENEWABLE: Final = frozenset(
    {
        "Biomass",
        "Geothermal",
        "Hydro Run-of-river and poundage",
        "Hydro Water Reservoir",
        "Marine",
        "Other renewable",
        "Solar",
        "Wind Offshore",
        "Wind Onshore",
    }
)
VARIABLE_RENEWABLE: Final = frozenset({"Solar", "Wind Offshore", "Wind Onshore"})
CORE_TYPES: Final = frozenset(
    {
        "Nuclear",
        "Fossil Gas",
        "Hydro Run-of-river and poundage",
        "Hydro Water Reservoir",
        "Solar",
        "Wind Onshore",
    }
)
MONTH_SEASON: Final[dict[int, str]] = {
    **dict.fromkeys((12, 1, 2), "winter"),
    **dict.fromkeys((3, 4, 5), "spring"),
    **dict.fromkeys((6, 7, 8), "summer"),
    **dict.fromkeys((9, 10, 11), "autumn"),
}


@dataclass(frozen=True)
class EmissionFactor:
    g_per_kwh: float
    source: str


_AR5 = "IPCC AR5 WGIII Annex III, Table A.III.2 (life-cycle median)"
_ASSUMED = "assumption (no AR5 median); small share of French output"

EMISSION_FACTORS: Final[dict[str, EmissionFactor]] = {
    "Nuclear": EmissionFactor(12, _AR5),
    "Wind Onshore": EmissionFactor(11, _AR5),
    "Wind Offshore": EmissionFactor(12, _AR5),
    "Solar": EmissionFactor(48, _AR5 + ", utility PV"),
    "Hydro Run-of-river and poundage": EmissionFactor(24, _AR5),
    "Hydro Water Reservoir": EmissionFactor(24, _AR5),
    "Geothermal": EmissionFactor(38, _AR5),
    "Marine": EmissionFactor(17, _AR5 + ", ocean"),
    "Biomass": EmissionFactor(230, _AR5 + ", dedicated biomass"),
    "Fossil Gas": EmissionFactor(490, _AR5 + ", gas combined cycle"),
    "Fossil Hard coal": EmissionFactor(820, _AR5 + ", pulverised coal"),
    "Fossil Brown coal/Lignite": EmissionFactor(820, _AR5 + ", pulverised coal"),
    "Fossil Coal-derived gas": EmissionFactor(820, _AR5 + ", pulverised coal (proxy)"),
    "Fossil Oil": EmissionFactor(650, _ASSUMED),
    "Waste": EmissionFactor(330, _ASSUMED),
    "Other renewable": EmissionFactor(230, _ASSUMED + " (biomass proxy)"),
    "Other": EmissionFactor(490, _ASSUMED + " (gas proxy)"),
}


def hourly(frame: pd.DataFrame) -> pd.DataFrame:
    """Hourly means on the UTC grid. An hour is NaN if any of its quarter-hours is missing."""
    grouped = frame.resample("1h")
    out = grouped.mean()
    complete = grouped.count() == 4
    return out.where(complete)


def production_columns(generation: pd.DataFrame) -> list[str]:
    names = [str(c) for c in generation.columns]
    return [c for c in names if not c.endswith(CONSUMPTION_SUFFIX) and c not in STORAGE]


def core_missing(generation: pd.DataFrame) -> pd.Series[bool]:
    """True where any core production type present in the frame is missing."""
    cols = [c for c in generation.columns if c in CORE_TYPES]
    return generation[cols].isna().any(axis=1)


def total_generation(generation: pd.DataFrame) -> pd.Series[float]:
    """Sum over production types, in MW.

    Minor types that are not reported at a timestamp (e.g. hard coal after its last plant
    stopped) count as 0. A timestamp where a *core* type is missing is NaN, so that gaps in, say,
    nuclear do not show up as a collapse of generation.
    """
    cols = production_columns(generation)
    total = generation[cols].sum(axis=1, min_count=1)
    return total.mask(core_missing(generation)).rename("generation_mw")


def variable_renewables(generation: pd.DataFrame) -> pd.Series[float]:
    cols = [c for c in generation if c in VARIABLE_RENEWABLE]
    total = generation[cols].sum(axis=1, min_count=1)
    return total.mask(core_missing(generation)).rename("wind_solar_mw")


def residual_load(load: pd.DataFrame, generation: pd.DataFrame) -> pd.Series[float]:
    """Actual load minus solar and wind, MW."""
    return (load["load_actual_mw"] - variable_renewables(generation)).rename("residual_load_mw")


def renewable_share(generation: pd.DataFrame) -> pd.Series[float]:
    cols = [c for c in generation if c in RENEWABLE]
    renewable = generation[cols].sum(axis=1, min_count=1).mask(core_missing(generation))
    return (renewable / total_generation(generation)).rename("renewable_share")


def co2_intensity(generation: pd.DataFrame) -> pd.Series[float]:
    """Production-based life-cycle intensity of domestic generation, gCO2eq/kWh."""
    cols = production_columns(generation)
    unknown = sorted(set(cols) - set(EMISSION_FACTORS))
    if unknown:
        msg = f"no emission factor for {unknown}"
        raise KeyError(msg)
    factors = pd.Series({c: EMISSION_FACTORS[c].g_per_kwh for c in cols})
    emissions = generation[cols].mul(factors, axis=1).sum(axis=1, min_count=1)
    emissions = emissions.mask(core_missing(generation))
    return (emissions / total_generation(generation)).rename("co2_g_per_kwh")


def net_imports(flows: pd.DataFrame) -> pd.DataFrame:
    """Net import per border (import - export, MW; negative = France exports) and the total."""
    borders = sorted({str(c).split("_", 1)[1] for c in flows.columns})
    out = pd.DataFrame(
        {b: flows[f"import_{b}"] - flows[f"export_{b}"] for b in borders}, index=flows.index
    )
    out["total"] = out.sum(axis=1, min_count=len(borders))
    return out


def season(index: pd.DatetimeIndex) -> pd.Index[str]:
    """Meteorological season of each local timestamp."""
    return pd.Index([MONTH_SEASON[m] for m in index.month], name="season")


def daily_profile(series: pd.Series[float], by: str = "season") -> pd.DataFrame:
    """Mean by Europe/Paris hour of day (rows) and season or day type (columns).

    ``by`` is ``"season"`` or ``"daytype"`` (weekday / saturday / sunday).
    """
    local = series.dropna()
    idx = pd.DatetimeIndex(local.index).tz_convert(LOCAL_TZ)
    if by == "season":
        groups: pd.Index[str] = season(idx)
    elif by == "daytype":
        kind = {5: "saturday", 6: "sunday"}
        groups = pd.Index([kind.get(d, "weekday") for d in idx.day_of_week], name="daytype")
    else:
        msg = f"unknown grouping {by!r}"
        raise ValueError(msg)
    frame = pd.DataFrame({"value": local.to_numpy(), "hour": idx.hour, by: groups})
    table = frame.pivot_table(index="hour", columns=by, values="value", aggfunc="mean")
    order = (
        ["winter", "spring", "summer", "autumn"]
        if by == "season"
        else ["weekday", "saturday", "sunday"]
    )
    return table[[c for c in order if c in table.columns]]


def monthly_summary(
    prices: pd.DataFrame, load: pd.DataFrame, generation: pd.DataFrame, flows: pd.DataFrame
) -> pd.DataFrame:
    """Monthly (Europe/Paris) averages of the headline indicators."""
    frame = pd.DataFrame(
        {
            "price_eur_mwh": prices["price_eur_mwh"],
            "load_gw": load["load_actual_mw"] / 1e3,
            "residual_load_gw": residual_load(load, generation) / 1e3,
            "generation_gw": total_generation(generation) / 1e3,
            "renewable_share": renewable_share(generation),
            "co2_g_per_kwh": co2_intensity(generation),
            "net_imports_gw": net_imports(flows)["total"] / 1e3,
            "negative_price_share": (prices["price_eur_mwh"] < 0)
            .astype(float)
            .where(prices["price_eur_mwh"].notna()),
        }
    )
    local = frame.tz_convert(LOCAL_TZ)
    return local.resample("MS").mean()
