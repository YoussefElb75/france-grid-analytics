"""ENTSO-E code lists used by this project (PSR = power system resource type)."""

from __future__ import annotations

from typing import Final

PSR_TYPES: Final[dict[str, str]] = {
    "B01": "Biomass",
    "B02": "Fossil Brown coal/Lignite",
    "B03": "Fossil Coal-derived gas",
    "B04": "Fossil Gas",
    "B05": "Fossil Hard coal",
    "B06": "Fossil Oil",
    "B07": "Fossil Oil shale",
    "B08": "Fossil Peat",
    "B09": "Geothermal",
    "B10": "Hydro Pumped Storage",
    "B11": "Hydro Run-of-river and poundage",
    "B12": "Hydro Water Reservoir",
    "B13": "Marine",
    "B14": "Nuclear",
    "B15": "Other renewable",
    "B16": "Solar",
    "B17": "Waste",
    "B18": "Wind Offshore",
    "B19": "Wind Onshore",
    "B20": "Other",
    "B25": "Energy storage",
}

CONSUMPTION_SUFFIX: Final = " (consumption)"


def psr_label(code: str) -> str:
    """Human-readable label for a PSR code; unknown codes are kept as-is."""
    return PSR_TYPES.get(code, code)
