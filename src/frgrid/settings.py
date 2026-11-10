"""Runtime settings: API token handling and local paths.

The ENTSO-E security token is read from the ``ENTSOE_API_TOKEN`` environment variable, or from a
git-ignored ``.env`` file. It is wrapped in :class:`SecretToken` so that it never shows up in a
``repr``, a log line, an exception message or a traceback by accident.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

TOKEN_ENV_VAR = "ENTSOE_API_TOKEN"  # noqa: S105 (variable name, not a secret)
PLACEHOLDER_TOKENS = frozenset({"", "your-token-here"})


class MissingTokenError(RuntimeError):
    """Raised when no usable ENTSO-E token is configured."""


@dataclass(frozen=True)
class SecretToken:
    """An opaque wrapper around the API token. Only :meth:`reveal` returns the raw value."""

    _value: str = field(repr=False)

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "SecretToken(***)"

    def __str__(self) -> str:
        return "***"


def project_root() -> Path:
    """Repository root: the first parent that holds ``pyproject.toml``, else the working dir."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def data_dir() -> Path:
    """Local, git-ignored data folder (override with ``FRGRID_DATA_DIR``)."""
    override = os.environ.get("FRGRID_DATA_DIR")
    return Path(override) if override else project_root() / "data"


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def load_token(dotenv: Path | None = None) -> SecretToken:
    """Return the configured token, or raise :class:`MissingTokenError` (without echoing it)."""
    value = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if not value:
        value = _read_dotenv(dotenv or project_root() / ".env").get(TOKEN_ENV_VAR, "")
    if value in PLACEHOLDER_TOKENS:
        msg = (
            f"No ENTSO-E token: set {TOKEN_ENV_VAR} in the environment or in a git-ignored .env "
            "file (see .env.example)."
        )
        raise MissingTokenError(msg)
    return SecretToken(value)
