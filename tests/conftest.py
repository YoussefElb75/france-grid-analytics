from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest


def fake_token() -> str:
    """A token-shaped fake value, assembled at runtime so no token-like literal sits in the repo."""
    return "-".join(["1a2b3c4d", "aaaa", "4bbb", "8ccc", "1234567890ab"])


@pytest.fixture
def token_value() -> str:
    return fake_token()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Tests never see the developer's real token, data folder or the network.

    * the token env var is removed and the project root (where ``.env`` is looked up) points to
      an empty temporary folder;
    * the data folder is a temporary folder;
    * any real HTTP request fails: tests must inject an ``httpx.MockTransport``.
    """
    root = tmp_path_factory.mktemp("root")
    monkeypatch.delenv("ENTSOE_API_TOKEN", raising=False)
    monkeypatch.setattr("frgrid.settings.project_root", lambda: Path(root))
    monkeypatch.setenv("FRGRID_DATA_DIR", str(tmp_path_factory.mktemp("data")))

    real_send = httpx.Client.send

    def guarded_send(self: httpx.Client, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        transport = self._transport
        if not isinstance(transport, httpx.MockTransport):
            msg = f"network access attempted in tests: {request.url.host}"
            raise RuntimeError(msg)
        return real_send(self, request, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)
