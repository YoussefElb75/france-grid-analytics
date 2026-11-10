"""EIC area codes used for France and its interconnected neighbours.

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

LOCAL_TZ: Final = "Europe/Paris"
