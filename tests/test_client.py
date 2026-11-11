from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import httpx
import pandas as pd
import pytest

from frgrid.client import TOKEN_HEADER, EntsoeAuthError, EntsoeClient, EntsoeError, format_period
from frgrid.settings import SecretToken

FIX = Path(__file__).parent / "fixtures"
START = pd.Timestamp("2026-10-31T23:00Z")
END = pd.Timestamp("2026-11-01T23:00Z")
PARAMS = {"documentType": "A44", "in_Domain": "10YFR-RTE------C", "out_Domain": "10YFR-RTE------C"}
NOW = pd.Timestamp("2026-11-30T00:00Z")


class Recorder:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0)


def ok(name: str = "prices_pt15m.xml") -> httpx.Response:
    return httpx.Response(200, content=(FIX / name).read_bytes())


def make(
    token_value: str,
    responses: list[httpx.Response],
    *,
    cache_dir: Path | None = None,
    now: pd.Timestamp = NOW,
    **kw: float,
) -> tuple[EntsoeClient, Recorder, list[float]]:
    rec = Recorder(responses)
    sleeps: list[float] = []
    clock = iter(range(1_000_000))
    monotonic: Callable[[], float] = lambda: float(next(clock))  # noqa: E731
    client = EntsoeClient(
        SecretToken(token_value),
        cache_dir=cache_dir,
        transport=httpx.MockTransport(rec),
        sleep=sleeps.append,
        monotonic=monotonic,
        now=lambda: now,
        **kw,  # type: ignore[arg-type]
    )
    return client, rec, sleeps


def test_token_only_in_header_never_in_url(token_value: str) -> None:
    client, rec, _ = make(token_value, [ok()])
    assert client.get(PARAMS, START, END) is not None
    (req,) = rec.requests
    assert req.headers[TOKEN_HEADER] == token_value
    assert token_value not in str(req.url)
    assert "securitytoken" not in str(req.url).lower()
    assert req.url.host == "web-api.tp.entsoe.eu"
    assert req.url.scheme == "https"
    assert req.url.params["periodStart"] == "202610312300"


def test_system_proxies_are_ignored(token_value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:8080")
    client, _, _ = make(token_value, [ok()])
    assert client._http.trust_env is False


def test_format_period_requires_tz_and_converts_to_utc() -> None:
    assert format_period(pd.Timestamp("2025-06-15", tz="Europe/Paris")) == "202506142200"
    with pytest.raises(ValueError, match="timezone-aware"):
        format_period(pd.Timestamp("2025-06-15"))


def test_retries_on_503_then_succeeds(token_value: str) -> None:
    client, rec, sleeps = make(token_value, [httpx.Response(503), httpx.Response(503), ok()])
    assert client.get(PARAMS, START, END) is not None
    assert len(rec.requests) == 3
    assert [s for s in sleeps if s >= 1] == [2.0, 4.0]


def test_retry_after_header_is_honoured(token_value: str) -> None:
    client, _, sleeps = make(token_value, [httpx.Response(429, headers={"Retry-After": "7"}), ok()])
    client.get(PARAMS, START, END)
    assert 7.0 in sleeps


def test_gives_up_with_a_message_free_of_the_token(token_value: str) -> None:
    client, rec, _ = make(token_value, [httpx.Response(503)] * 3, max_retries=2)
    with pytest.raises(EntsoeError) as info:
        client.get(PARAMS, START, END)
    assert len(rec.requests) == 3
    assert token_value not in str(info.value)
    assert "A44" in str(info.value)


def test_transport_errors_are_retried(token_value: str) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return ok()

    client = EntsoeClient(
        SecretToken(token_value), transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    assert client.get(PARAMS, START, END) is not None
    assert calls["n"] == 2


def test_auth_error_is_not_retried(token_value: str) -> None:
    client, rec, _ = make(token_value, [httpx.Response(401, text="Unauthorized")])
    with pytest.raises(EntsoeAuthError) as info:
        client.get(PARAMS, START, END)
    assert len(rec.requests) == 1
    assert token_value not in str(info.value)


def test_no_matching_data_returns_none(token_value: str) -> None:
    client, _, _ = make(token_value, [ok("ack_no_data.xml")])
    assert client.get(PARAMS, START, END) is None


def test_real_400_error_is_raised_not_swallowed(token_value: str) -> None:
    body = (FIX / "ack_interval_too_large.xml").read_bytes()
    client, _, _ = make(token_value, [httpx.Response(400, content=body)])
    with pytest.raises(EntsoeError, match="larger than maximum allowed period"):
        client.get(PARAMS, START, END)


def test_rate_limit_spaces_requests(token_value: str) -> None:
    # The fake monotonic clock advances 1 s per reading; ask for 5 s between requests.
    client, _, sleeps = make(token_value, [ok(), ok()], min_interval=5.0)
    client.get(PARAMS, START, END)
    client.get(PARAMS, START, END + pd.Timedelta(days=1))
    assert any(0 < s <= 5.0 for s in sleeps)


def test_settled_windows_are_cached_without_the_token(token_value: str, tmp_path: Path) -> None:
    client, rec, _ = make(token_value, [ok()], cache_dir=tmp_path)
    first = client.get(PARAMS, START, END)
    second = client.get(PARAMS, START, END)
    assert first == second
    assert len(rec.requests) == 1
    files = list(tmp_path.rglob("*"))
    assert any(f.suffix == ".xml" for f in files)
    for f in files:
        assert token_value not in f.name
        if f.is_file():
            assert token_value.encode() not in f.read_bytes()


def test_recent_windows_are_not_cached(token_value: str, tmp_path: Path) -> None:
    client, rec, _ = make(token_value, [ok(), ok()], cache_dir=tmp_path, now=END)
    client.get(PARAMS, START, END)
    client.get(PARAMS, START, END)
    assert len(rec.requests) == 2
    assert not list(tmp_path.rglob("*.xml"))


def test_no_data_is_cached_as_a_marker(token_value: str, tmp_path: Path) -> None:
    client, rec, _ = make(token_value, [ok("ack_no_data.xml")], cache_dir=tmp_path)
    assert client.get(PARAMS, START, END) is None
    assert client.get(PARAMS, START, END) is None
    assert len(rec.requests) == 1


def test_logs_never_contain_the_token(token_value: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    client, _, _ = make(token_value, [httpx.Response(503), ok()])
    client.get(PARAMS, START, END)
    logging.getLogger("httpx").info("simulated third-party line with %s", token_value)
    assert caplog.records
    assert token_value not in caplog.text
