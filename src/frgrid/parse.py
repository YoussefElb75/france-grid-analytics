"""Parse ENTSO-E XML market documents into pandas objects.

Conventions
-----------
* Every timestamp is a tz-aware UTC ``Timestamp`` marking the *start* of a delivery interval,
  exactly as ENTSO-E publishes it (``timeInterval/start`` is UTC).
* A ``Period`` holds ``Point`` elements numbered by ``position`` (1-based) on a grid of
  ``resolution`` (PT15M, PT30M, PT60M ...).
* ``curveType`` A01 ("sequential fixed size block") lists every position. ``curveType`` A03
  ("variable sized block") omits a position whenever its value equals the previous one; the
  value is carried forward until the next listed position or the end of the period. All
  French documents probed in 2026 use A03, so forward filling is essential.
* Values can be expanded to a finer grid (e.g. hourly -> 15 min) by repetition, which is exact
  for average power (MW) and for prices that hold over the whole interval.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np
import pandas as pd

ACK_ROOT = "Acknowledgement_MarketDocument"

_RES_RE = re.compile(r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?)?$")


class ParseError(ValueError):
    """The document does not have the expected structure."""


class AcknowledgementError(ValueError):
    """ENTSO-E answered with an acknowledgement (error) document instead of data."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"ENTSO-E acknowledgement {code}: {text}")
        self.code = code
        self.text = text

    @property
    def no_data(self) -> bool:
        # ENTSO-E uses reason code 999 for "no matching data" *and* for real errors (e.g. an
        # interval longer than allowed), so the text is what tells them apart.
        return "no matching data" in self.text.lower()


@dataclass(frozen=True)
class TimeSeries:
    """One ``TimeSeries`` element: its scalar metadata and its values on a regular grid."""

    meta: dict[str, str]
    values: pd.Series[float]
    resolution: pd.Timedelta


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(elem: ET.Element, name: str) -> ET.Element | None:
    for child in elem:
        if _local(child.tag) == name:
            return child
    return None


def _text(elem: ET.Element, name: str) -> str:
    child = _child(elem, name)
    if child is None or child.text is None:
        msg = f"missing <{name}> in <{_local(elem.tag)}>"
        raise ParseError(msg)
    return child.text.strip()


def parse_resolution(text: str) -> pd.Timedelta:
    """ISO 8601 duration as used by ENTSO-E (``PT15M``, ``PT60M``, ``PT1H``, ``P1D``)."""
    m = _RES_RE.match(text.strip())
    if not m or not any(m.groupdict().values()):
        msg = f"unsupported resolution {text!r}"
        raise ParseError(msg)
    g = {k: int(v) if v else 0 for k, v in m.groupdict().items()}
    return pd.Timedelta(days=g["days"], hours=g["hours"], minutes=g["minutes"])


def utc(text: str) -> pd.Timestamp:
    ts = pd.Timestamp(text)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def check_acknowledgement(root: ET.Element) -> None:
    """Raise :class:`AcknowledgementError` if ``root`` is an acknowledgement document."""
    if _local(root.tag) != ACK_ROOT:
        return
    reason = _child(root, "Reason")
    code = _text(reason, "code") if reason is not None else ""
    text = ""
    if reason is not None and (t := _child(reason, "text")) is not None and t.text:
        text = t.text.strip()
    raise AcknowledgementError(code, text)


def _period(
    period: ET.Element, value_tag: str, curve: str
) -> tuple[pd.Series[float], pd.Timedelta]:
    interval = _child(period, "timeInterval")
    if interval is None:
        msg = "missing <timeInterval> in <Period>"
        raise ParseError(msg)
    start, end = utc(_text(interval, "start")), utc(_text(interval, "end"))
    res = parse_resolution(_text(period, "resolution"))
    n_slots = (end - start) / res
    if n_slots <= 0 or n_slots != int(n_slots):
        msg = f"period {start}..{end} is not a whole number of {res} slots"
        raise ParseError(msg)
    n = int(n_slots)
    values = np.full(n, np.nan)
    listed = np.zeros(n, dtype=bool)
    for point in period:
        if _local(point.tag) != "Point":
            continue
        pos = int(_text(point, "position"))
        if not 1 <= pos <= n:
            msg = f"position {pos} outside 1..{n}"
            raise ParseError(msg)
        values[pos - 1] = float(_text(point, value_tag))
        listed[pos - 1] = True
    if curve == "A03":
        if n and not listed[0]:
            msg = "A03 curve without a first position"
            raise ParseError(msg)
        idx = np.where(listed, np.arange(n), 0)
        np.maximum.accumulate(idx, out=idx)
        values = values[idx]
    index = pd.date_range(start, periods=n, freq=res, tz="UTC", name="time_utc")
    return pd.Series(values, index=index, dtype="float64"), res


def parse_document(content: bytes, value_tag: str) -> list[TimeSeries]:
    """Parse a Publication/GL market document.

    ``value_tag`` is ``"price.amount"`` for prices and ``"quantity"`` for volumes (MW).
    Raises :class:`AcknowledgementError` for acknowledgement documents.
    """
    root = ET.fromstring(content)
    check_acknowledgement(root)
    out: list[TimeSeries] = []
    for ts in root:
        if _local(ts.tag) != "TimeSeries":
            continue
        meta: dict[str, str] = {}
        for child in ts:
            name = _local(child.tag)
            if name == "MktPSRType":
                psr = _child(child, "psrType")
                if psr is not None and psr.text:
                    meta["psrType"] = psr.text.strip()
            elif len(child) == 0 and child.text and child.text.strip():
                meta[name] = child.text.strip()
        curve = meta.get("curveType", "A01")
        pieces: list[pd.Series[float]] = []
        resolutions: set[pd.Timedelta] = set()
        for period in ts:
            if _local(period.tag) == "Period":
                values, res = _period(period, value_tag, curve)
                pieces.append(values)
                resolutions.add(res)
        if not pieces:
            continue
        if len(resolutions) != 1:
            msg = "a TimeSeries mixes resolutions; expected one per series"
            raise ParseError(msg)
        series = pd.concat(pieces).sort_index()
        series = series[~series.index.duplicated(keep="first")]
        out.append(TimeSeries(meta=meta, values=series, resolution=resolutions.pop()))
    return out


def expand(
    values: pd.Series[float], native: pd.Timedelta, target: pd.Timedelta
) -> pd.Series[float]:
    """Repeat each value onto a finer regular grid (``target`` must divide ``native``)."""
    if native == target:
        return values
    ratio = native / target
    if target > native or ratio != int(ratio):
        msg = f"cannot expand {native} to {target}"
        raise ValueError(msg)
    k = int(ratio)
    offsets = pd.to_timedelta(np.tile(np.arange(k) * target.value, len(values)), unit="ns")
    index = pd.DatetimeIndex(np.repeat(values.index.to_numpy(), k)) + offsets
    index = index.tz_localize("UTC") if index.tz is None else index
    return pd.Series(np.repeat(values.to_numpy(), k), index=index.rename(values.index.name))
