from __future__ import annotations

import pytest


def fake_token() -> str:
    """A token-shaped fake value, assembled at runtime so no token-like literal sits in the repo."""
    return "-".join(["1a2b3c4d", "aaaa", "4bbb", "8ccc", "1234567890ab"])


@pytest.fixture
def token_value() -> str:
    return fake_token()


@pytest.fixture(autouse=True)
def _no_real_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Tests never see the developer's real token or data folder."""
    monkeypatch.delenv("ENTSOE_API_TOKEN", raising=False)
    monkeypatch.setenv("FRGRID_DATA_DIR", str(tmp_path_factory.mktemp("data")))
