"""Minimal, careful HTTP client for the ENTSO-E Transparency Platform RESTful API.

Security
--------
* The token travels only in the ``SECURITY_TOKEN`` request header, never in the URL, so URLs,
  cache keys, logs and error messages cannot contain it.
* Requests go straight to ``https://web-api.tp.entsoe.eu/api``: system proxy settings are
  ignored (``trust_env=False``) and redirects are not followed.
* Error messages are built from the query parameters and ENTSO-E's reason text only.

Robustness
----------
* Rate limiting: at most one request every ``min_interval`` seconds (default 0.25 s, i.e. at most
  240 requests per minute; ENTSO-E allows 400 per minute per user).
* Retries with exponential back-off on HTTP 429/5xx and transport errors, honouring
  ``Retry-After``.
* A local cache of raw XML answers (git-ignored), keyed by the query parameters. Only windows
  that ended more than ``settle_days`` ago are cached, because recent data still get revised.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx
import pandas as pd

from frgrid.parse import AcknowledgementError, check_acknowledgement
from frgrid.settings import SecretToken

BASE_URL = "https://web-api.tp.entsoe.eu/api"
TOKEN_HEADER = "SECURITY_TOKEN"  # noqa: S105 (header name, not a secret)
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
NO_DATA = b""  # cache marker content for "no matching data"

log = logging.getLogger(__name__)
_UUID_RE = re.compile(r"[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}")


class _RedactFilter(logging.Filter):
    """Defence in depth: scrub token-like strings from third-party HTTP log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if _UUID_RE.search(message):
            record.msg = _UUID_RE.sub("***", message)
            record.args = None
        return True


for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).addFilter(_RedactFilter())


class EntsoeError(RuntimeError):
    """Any failure talking to ENTSO-E. Messages never contain the token."""


class EntsoeAuthError(EntsoeError):
    """HTTP 401/403: the token is missing, invalid or not enabled for the API."""


def format_period(ts: pd.Timestamp) -> str:
    """ENTSO-E period boundary: UTC, ``yyyyMMddHHmm``."""
    if ts.tzinfo is None:
        msg = "timestamps must be timezone-aware"
        raise ValueError(msg)
    return ts.tz_convert("UTC").strftime("%Y%m%d%H%M")


def _describe(params: Mapping[str, str]) -> str:
    keys = ("documentType", "processType", "in_Domain", "out_Domain", "outBiddingZone_Domain")
    parts = [f"{k}={params[k]}" for k in keys if k in params]
    return f"{' '.join(parts)} {params.get('periodStart')}-{params.get('periodEnd')}"


class EntsoeClient:
    def __init__(
        self,
        token: SecretToken,
        *,
        cache_dir: Path | None = None,
        min_interval: float = 0.25,
        max_retries: int = 5,
        backoff_base: float = 2.0,
        max_backoff: float = 60.0,
        timeout: float = 90.0,
        settle_days: int = 7,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], pd.Timestamp] = lambda: pd.Timestamp.now(tz="UTC"),
    ) -> None:
        self._token = token
        self.cache_dir = cache_dir
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.max_backoff = max_backoff
        self.settle = pd.Timedelta(days=settle_days)
        self._sleep = sleep
        self._monotonic = monotonic
        self._now = now
        self._last_request: float | None = None
        self.requests_made = 0
        self._http = httpx.Client(
            timeout=timeout, trust_env=False, follow_redirects=False, transport=transport
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> EntsoeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- cache -------------------------------------------------------------------------------
    def _cache_path(self, params: Mapping[str, str]) -> Path | None:
        if self.cache_dir is None:
            return None
        key = hashlib.sha256(json.dumps(sorted(params.items())).encode()).hexdigest()[:32]
        return self.cache_dir / params.get("documentType", "misc") / f"{key}.xml"

    def _cacheable(self, end: pd.Timestamp) -> bool:
        return end <= self._now() - self.settle

    # ---- HTTP --------------------------------------------------------------------------------
    def _throttle(self) -> None:
        if self._last_request is not None:
            wait = self.min_interval - (self._monotonic() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._monotonic()

    def _backoff(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None and (ra := response.headers.get("Retry-After")):
            try:
                return min(float(ra), self.max_backoff)
            except ValueError:
                pass
        return float(min(self.backoff_base * 2**attempt, self.max_backoff))

    def get(
        self,
        params: Mapping[str, str],
        start: pd.Timestamp,
        end: pd.Timestamp,
        *,
        refresh: bool = False,
    ) -> bytes | None:
        """Raw XML for one query window, or ``None`` when ENTSO-E has no matching data."""
        query = {**params, "periodStart": format_period(start), "periodEnd": format_period(end)}
        what = _describe(query)
        path = self._cache_path(query)
        if path is not None and path.is_file() and not refresh:
            cached = path.read_bytes()
            return None if cached == NO_DATA else cached

        content = self._fetch(query, what)
        if path is not None and self._cacheable(end):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(NO_DATA if content is None else content)
        return content

    def _fetch(self, query: Mapping[str, str], what: str) -> bytes | None:
        headers = {TOKEN_HEADER: self._token.reveal(), "Accept": "application/xml"}
        for attempt in range(self.max_retries + 1):
            self._throttle()
            response: httpx.Response | None = None
            try:
                response = self._http.get(BASE_URL, params=dict(query), headers=headers)
                self.requests_made += 1
            except httpx.TransportError as exc:
                problem = f"transport error ({type(exc).__name__})"
            else:
                status = response.status_code
                if status == 200:
                    return self._payload(response.content, what)
                if status in (401, 403):
                    msg = f"ENTSO-E refused the token (HTTP {status}) for {what}"
                    raise EntsoeAuthError(msg)
                if status == 400:
                    return self._payload(response.content, what, http_status=400)
                if status not in RETRY_STATUSES:
                    msg = f"ENTSO-E HTTP {status} for {what}"
                    raise EntsoeError(msg)
                problem = f"HTTP {status}"
            if attempt == self.max_retries:
                msg = f"ENTSO-E {problem} for {what}; gave up after {attempt + 1} attempts"
                raise EntsoeError(msg)
            delay = self._backoff(attempt, response)
            log.warning("%s for %s; retrying in %.1f s", problem, what, delay)
            self._sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _payload(content: bytes, what: str, http_status: int = 200) -> bytes | None:
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            msg = f"ENTSO-E HTTP {http_status} with a non-XML body for {what}"
            raise EntsoeError(msg) from None
        try:
            check_acknowledgement(root)
        except AcknowledgementError as ack:
            if ack.no_data:
                log.info("no matching data for %s", what)
                return None
            text = _UUID_RE.sub("***", ack.text)[:300]
            msg = f"ENTSO-E rejected {what}: {ack.code} {text}"
            raise EntsoeError(msg) from None
        if http_status != 200:
            msg = f"ENTSO-E HTTP {http_status} for {what}"
            raise EntsoeError(msg)
        return content
