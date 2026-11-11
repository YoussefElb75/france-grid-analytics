"""Turn a saved ENTSO-E response into a small, scrubbed test fixture.

* Replaces document and time-series ``mRID`` identifiers with neutral placeholders (area EIC
  codes such as ``10YFR-RTE------C`` are public and kept).
* Optionally keeps only some PSR types, to keep generation fixtures small.
* Replaces every published value (``price.amount`` / ``quantity``) with a deterministic synthetic
  value ``base + step * position`` (``--base``/``--step``), so no real data series end up in the
  repository; the document structure (periods, resolutions, omitted A03 positions) is kept.
* Refuses to write anything that still contains a token-like string or the local token.

Usage::

    python scripts/scrub_fixture.py data/probe/A75_gen.xml tests/fixtures/generation.xml \
        --psr B04 B10 B14 B16 B18 B19
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _scanner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_secrets", ROOT / "scripts" / "check_secrets.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_secrets"] = module
    spec.loader.exec_module(module)
    return module


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def synthesize(root: ET.Element, base: float, step: float) -> None:
    """Overwrite each point's value with ``base + step * position`` (series index adds 0.1*base)."""
    series = [c for c in root if _local(c.tag) == "TimeSeries"]
    for i, ts in enumerate(series):
        for point in (e for e in ts.iter() if _local(e.tag) == "Point"):
            pos = next(int(c.text or "0") for c in point if _local(c.tag) == "position")
            for c in point:
                if _local(c.tag) in ("price.amount", "quantity"):
                    c.text = f"{base * (1 + 0.1 * i) + step * pos:.2f}"


def scrub(
    content: bytes,
    keep_psr: set[str] | None = None,
    synthetic: tuple[float, float] | None = None,
) -> bytes:
    root = ET.fromstring(content)  # noqa: S314 (local file we downloaded ourselves)
    ns = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
    if ns:
        ET.register_namespace("", ns)
    for child in root:
        if _local(child.tag) == "mRID":
            child.text = "fixture-document"
    series = [c for c in root if _local(c.tag) == "TimeSeries"]
    for i, ts in enumerate(series, start=1):
        psr = next((e.text for e in ts.iter() if _local(e.tag) == "psrType"), None)
        if keep_psr is not None and psr not in keep_psr:
            root.remove(ts)
            continue
        for child in ts:
            if _local(child.tag) == "mRID":
                child.text = f"fixture-ts-{i}"
    if synthetic is not None:
        synthesize(root, *synthetic)
    return bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--psr", nargs="+", help="keep only these PSR types (generation)")
    parser.add_argument("--base", type=float, default=100.0, help="synthetic value base")
    parser.add_argument("--step", type=float, default=1.0, help="synthetic value step per position")
    parser.add_argument(
        "--keep-values", action="store_true", help="keep real values (never commit)"
    )
    args = parser.parse_args(argv)

    synthetic = None if args.keep_values else (args.base, args.step)
    data = scrub(args.source.read_bytes(), set(args.psr) if args.psr else None, synthetic)
    cs = _scanner()
    findings = cs.scan_bytes(str(args.target), data, cs._local_token_variants(ROOT))
    if findings:
        for f in findings:
            print(f)
        print("refusing to write a fixture with token-like content")
        return 1
    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_bytes(data)
    print(f"{args.target} ({len(data):,} bytes) clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
