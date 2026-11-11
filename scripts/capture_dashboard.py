"""Capture README screenshots and a short demo GIF of the dashboard with Playwright.

Starts ``frgrid dashboard`` on localhost with the locally stored data, drives a *headless*
Chromium (so images contain the page only: no browser window, address bar, bookmarks or
extensions), screenshots each tab, and assembles a GIF tour of the tabs. Images are re-encoded
with Pillow (no metadata) and scanned for token-like strings before being kept.

Requires the ``screenshots`` extra and ``python -m playwright install chromium``.

Usage::

    python scripts/capture_dashboard.py --out docs/img
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from types import ModuleType

from PIL import Image
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
# tab label -> (file name, number of charts the tab shows)
TABS = {
    "Prices": ("dashboard_prices.png", 3),
    "System": ("dashboard_system.png", 4),
    "Cross-border flows": ("dashboard_flows.png", 2),
}
WIDTH = 1360
HIDE_CHROME_CSS = """
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stStatusWidget"] { display: none !important; }
"""


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


def _wait_healthy(port: int, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://localhost:{port}/_stcore/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    msg = "dashboard did not start"
    raise RuntimeError(msg)


VISIBLE_CHARTS_JS = """(n) => {
    const imgs = Array.from(document.querySelectorAll('[data-testid="stImage"] img, img'))
        .filter(i => i.offsetParent !== null && i.naturalWidth > 0 && i.complete);
    const busy = document.body.innerText.includes('Running the walk-forward backtest');
    return !busy && imgs.length >= n;
}"""


def _settle(page: Page, charts: int = 0) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_function(VISIBLE_CHARTS_JS, arg=charts, timeout=180_000)
    page.wait_for_timeout(1500)


def _clean_png(raw: bytes, max_width: int | None = None) -> Image.Image:
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    if max_width is not None and img.width > max_width:
        img = img.resize(
            (max_width, round(img.height * max_width / img.width)), Image.Resampling.LANCZOS
        )
    return img


def _content_height(page: Page) -> int:
    height = page.evaluate(
        "() => Math.max(...Array.from(document.querySelectorAll('*')).map(e => e.scrollHeight))"
    )
    return int(height) + 40


def capture(out: Path, port: int) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen(
        [sys.executable, "-m", "frgrid.cli", "dashboard", "--port", str(port)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    written: list[Path] = []
    frames: list[Image.Image] = []
    try:
        _wait_healthy(port)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": WIDTH, "height": 900}, device_scale_factor=1)
            page.goto(f"http://localhost:{port}/")
            page.add_style_tag(content=HIDE_CHROME_CSS)
            _settle(page)
            for tab, (filename, charts) in TABS.items():
                page.get_by_role("tab", name=tab).click()
                _settle(page, charts)
                page.set_viewport_size({"width": WIDTH, "height": 900})
                frames.append(_clean_png(page.screenshot(), max_width=960))
                page.set_viewport_size({"width": WIDTH, "height": _content_height(page)})
                _settle(page, charts)
                full = _clean_png(page.screenshot(), max_width=1200)
                path = out / filename
                full.save(path, optimize=True)
                written.append(path)
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=30)

    gif = out / "dashboard_tour.gif"
    palette = [f.convert("P", palette=Image.Palette.ADAPTIVE, colors=128) for f in frames]
    palette[0].save(
        gif, save_all=True, append_images=palette[1:], duration=2200, loop=0, optimize=True
    )
    written.append(gif)

    cs = _scanner()
    tokens = cs._local_token_variants(ROOT)
    for path in written:
        findings = cs.scan_bytes(path.name, path.read_bytes(), tokens)
        if findings:
            path.unlink()
            msg = f"{path.name}: token-like content found; image deleted"
            raise RuntimeError(msg)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "img")
    parser.add_argument("--port", type=int, default=8519)
    args = parser.parse_args(argv)
    for path in capture(args.out, args.port):
        print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB), scan clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
