from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_secrets", ROOT / "scripts" / "check_secrets.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_secrets"] = module
    spec.loader.exec_module(module)
    return module


cs = _load()


def rules(data: bytes, tokens: tuple[bytes, ...] = ()) -> list[str]:
    return [f.rule for f in cs.scan_bytes("x", data, tokens)]


def test_uuid_is_blocked(token_value: str) -> None:
    assert rules(f"KEY = '{token_value}'".encode()) == ["uuid"]
    assert rules(token_value.upper().encode()) == ["uuid"]


def test_zero_uuid_placeholder_allowed() -> None:
    assert rules(b"00000000-0000-0000-0000-000000000000") == []


def test_query_param_blocked_but_placeholders_allowed() -> None:
    param = "security" + "Token=abcdef123"  # assembled so the literal never sits in the repo
    assert rules(f"?{param}".encode()) == ["security-token-param"]
    assert rules(b"?securityToken=***&x=1") == []
    assert rules(b"url = f'...?securityToken={token}'") == []


def test_local_token_variants(token_value: str) -> None:
    undashed = token_value.replace("-", "").upper().encode()
    tokens = (token_value.encode(), token_value.replace("-", "").encode())
    assert rules(b"blob " + undashed, tokens) == ["local-token"]


def test_findings_do_not_echo_the_secret(token_value: str) -> None:
    findings = cs.scan_bytes("f.py", token_value.encode(), ())
    assert findings
    assert all(token_value not in str(f) for f in findings)


@pytest.mark.parametrize(
    ("name", "blocked"), [(".env", True), ("a/.env.local", True), (".env.example", False)]
)
def test_dotenv_files(name: str, blocked: bool) -> None:
    found = cs.run([(name, b"")], [])
    assert bool(found) is blocked


def test_clean_text_passes() -> None:
    assert rules(b"documentType=A44&in_Domain=10YFR-RTE------C") == []
