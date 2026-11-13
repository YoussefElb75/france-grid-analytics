"""EIC area codes used for France, its interconnected neighbours and the European price zones.

Physical flows (document A11) are queried border by border against France's bidding zone. For
Germany and Italy the bidding zones adjacent to France are used (DE-LU and IT-North).
"""

from __future__ import annotations

from typing import Final

FRANCE: Final = "10YFR-RTE------C"

NEIGHBOURS: Final[dict[str, str]] = {
    "BE": "10YBE----------2",  # Belgium
    "CH": "10YCH-SWISSGRIDZ",  # Switzerland
    "DE": "10Y1001A1001A82H",  # Germany-Luxembourg bidding zone
    "ES": "10YES-REE------0",  # Spain
    "GB": "10YGB----------A",  # Great Britain
    "IT": "10Y1001A1001A73I",  # Italy North bidding zone
}

PRICE_ZONES: Final[dict[str, str]] = {
    "FR": FRANCE,
    "DE_LU": "10Y1001A1001A82H",
    "BE": "10YBE----------2",
    "NL": "10YNL----------L",
    "ES": "10YES-REE------0",
    "IT_NORTH": "10Y1001A1001A73I",
}
"""Day-ahead bidding zones compared in the European analysis (all coupled in SDAC)."""

ZONE_LABELS: Final[dict[str, str]] = {
    "FR": "France",
    "DE_LU": "Germany-Lux.",
    "BE": "Belgium",
    "NL": "Netherlands",
    "ES": "Spain",
    "IT_NORTH": "Italy North",
}

FLOW_BORDER: Final[dict[str, str]] = {"BE": "BE", "DE_LU": "DE", "ES": "ES", "IT_NORTH": "IT"}
"""Price zone -> suffix of its border columns in the ``flows`` dataset (NL has no FR border)."""

NTC_BORDERS: Final[dict[str, str]] = {"ES": PRICE_ZONES["ES"], "IT_NORTH": PRICE_ZONES["IT_NORTH"]}
"""Borders of France with a day-ahead NTC on ENTSO-E (BE and DE-LU are flow-based, in Core)."""

LOCAL_TZ: Final = "Europe/Paris"
