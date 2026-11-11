from __future__ import annotations

from pathlib import Path

import pytest

from frgrid.settings import MissingTokenError, SecretToken, load_token


def test_token_from_env(monkeypatch: pytest.MonkeyPatch, token_value: str, tmp_path: Path) -> None:
    monkeypatch.setenv("ENTSOE_API_TOKEN", token_value)
    assert load_token(tmp_path / "missing.env").reveal() == token_value


def test_token_from_dotenv(token_value: str, tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(f"# comment\nENTSOE_API_TOKEN='{token_value}'\n", encoding="utf-8")
    assert load_token(env).reveal() == token_value


@pytest.mark.parametrize(
    "content", ["", "ENTSOE_API_TOKEN=\n", "ENTSOE_API_TOKEN=your-token-here\n"]
)
def test_missing_or_placeholder_token(content: str, tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(content, encoding="utf-8")
    with pytest.raises(MissingTokenError):
        load_token(env)


def test_secret_token_never_renders(token_value: str) -> None:
    tok = SecretToken(token_value)
    assert token_value not in repr(tok)
    assert token_value not in str(tok)
    assert token_value not in f"{tok} {tok!r} {[tok]}"


def test_tests_cannot_see_the_real_dotenv() -> None:
    # conftest points the project root to an empty folder, so the developer's .env is invisible.
    with pytest.raises(MissingTokenError):
        load_token()


def test_tests_cannot_reach_the_network() -> None:
    import httpx  # noqa: PLC0415

    with httpx.Client() as client, pytest.raises(RuntimeError, match="network access"):
        client.get("https://example.invalid/")
