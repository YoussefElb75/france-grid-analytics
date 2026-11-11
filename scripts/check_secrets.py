"""Block token-like strings from entering the repository.

Used by the git pre-commit hook (``--staged``) and by CI (``--all``). Standard library only.
Findings are reported as ``path:line rule`` and never print the matching text.

Rules
-----
* ``uuid``: any 8-4-4-4-12 hex string (the ENTSO-E token format). The all-zero UUID is allowed
  as a placeholder.
* ``security-token-param``: a ``securityToken=`` query parameter followed by a literal value.
* ``local-token``: the exact token configured in the local ``.env`` / environment (also without
  dashes or in another case). Only effective on machines that have a token; CI has none.
* ``dotenv-file``: a ``.env`` file (other than ``.env.example``) is being committed.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

UUID_RE = re.compile(
    rb"(?<![0-9A-Fa-f])[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}(?![0-9A-Fa-f])"
)
ALLOWED_UUIDS = frozenset({b"00000000-0000-0000-0000-000000000000"})
PARAM_RE = re.compile(rb"securityToken=([^&\s'\"`<>{}()$]+)", re.IGNORECASE)
ALLOWED_PARAM_VALUES = frozenset({b"***", b"REDACTED", b"your-token-here", b"..."})
TOKEN_ENV_VAR = "ENTSOE_API_TOKEN"  # noqa: S105 (variable name, not a secret)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}"


def _local_token_variants(root: Path) -> list[bytes]:
    value = os.environ.get(TOKEN_ENV_VAR, "").strip()
    env_file = root / ".env"
    if not value and env_file.is_file():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, val = raw.strip().partition("=")
            if sep and key.strip() == TOKEN_ENV_VAR:
                value = val.strip().strip("'\"")
    if len(value) < 8 or value == "your-token-here":
        return []
    variants = {value, value.replace("-", "")}
    return sorted({v.lower().encode() for v in variants})


def scan_bytes(path: str, data: bytes, local_tokens: Iterable[bytes] = ()) -> list[Finding]:
    findings: list[Finding] = []
    tokens = list(local_tokens)
    for lineno, line in enumerate(data.splitlines(), start=1):
        for m in UUID_RE.finditer(line):
            if m.group(0).lower() not in ALLOWED_UUIDS:
                findings.append(Finding(path, lineno, "uuid"))
        for m in PARAM_RE.finditer(line):
            if m.group(1) not in ALLOWED_PARAM_VALUES:
                findings.append(Finding(path, lineno, "security-token-param"))
        lowered = line.lower()
        if any(t in lowered for t in tokens):
            findings.append(Finding(path, lineno, "local-token"))
    return findings


def _is_dotenv(path: str) -> bool:
    name = Path(path.split(" @", 1)[0]).name  # history entries look like "path @sha"
    return (name == ".env" or name.startswith(".env.")) and name != ".env.example"


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def _staged(root: Path) -> Iterator[tuple[str, bytes]]:
    names = _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    for name in filter(None, names.decode().split("\0")):
        yield name, _git(root, "show", f":{name}")


def _history(root: Path) -> Iterator[tuple[str, bytes]]:
    """Every blob reachable from any ref (all versions of all files) and every commit message."""
    listing = _git(root, "rev-list", "--objects", "--all").decode().splitlines()
    seen: set[str] = set()
    for line in listing:
        sha, _, path = line.partition(" ")
        if sha in seen:
            continue
        seen.add(sha)
        kind = _git(root, "cat-file", "-t", sha).decode().strip()
        if kind == "blob":
            yield f"{path or sha} @{sha[:8]}", _git(root, "cat-file", "blob", sha)
        elif kind == "commit":
            yield f"commit message @{sha[:8]}", _git(root, "log", "-1", "--format=%B", sha)


def _tracked(root: Path) -> Iterator[tuple[str, bytes]]:
    names = _git(root, "ls-files", "-z")
    for name in filter(None, names.decode().split("\0")):
        p = root / name
        if p.is_file():
            yield name, p.read_bytes()


def _paths(paths: Iterable[str]) -> Iterator[tuple[str, bytes]]:
    for name in paths:
        p = Path(name)
        if p.is_dir():
            for child in sorted(p.rglob("*")):
                skip = {
                    ".git",
                    ".venv",
                    "__pycache__",
                    ".mypy_cache",
                    ".ruff_cache",
                    ".pytest_cache",
                }
                if child.is_file() and not skip.intersection(child.parts):
                    yield str(child), child.read_bytes()
        elif p.is_file():
            yield name, p.read_bytes()


def run(files: Iterable[tuple[str, bytes]], local_tokens: Iterable[bytes]) -> list[Finding]:
    tokens = list(local_tokens)
    findings: list[Finding] = []
    for name, data in files:
        if _is_dotenv(name):
            findings.append(Finding(name, 0, "dotenv-file"))
            continue
        findings.extend(scan_bytes(name, data, tokens))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="scan files staged for commit")
    mode.add_argument("--all", action="store_true", help="scan all tracked files")
    mode.add_argument("--paths", nargs="+", help="scan these files or folders")
    mode.add_argument(
        "--history", action="store_true", help="scan every blob and message in history"
    )
    args = parser.parse_args(argv)

    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
    if args.staged:
        files = _staged(root)
    elif args.all:
        files = _tracked(root)
    elif args.history:
        files = _history(root)
    else:
        files = _paths(args.paths)
    findings = run(files, _local_token_variants(root))
    for f in findings:
        print(f, file=sys.stderr)
    if findings:
        print(f"check_secrets: {len(findings)} finding(s); commit blocked.", file=sys.stderr)
        return 1
    print("check_secrets: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
