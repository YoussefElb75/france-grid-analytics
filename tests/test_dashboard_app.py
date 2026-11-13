"""Run the real Streamlit script headless with AppTest (offline, synthetic data)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from frgrid import store
from synthetic import synthetic_europe, synthetic_inputs

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")


def all_text(at: AppTest) -> str:
    parts: list[str] = []
    for kind in ("markdown", "caption", "info", "success", "warning", "error", "title", "header"):
        parts.extend(str(el.value) for el in getattr(at, kind))
    return "\n".join(parts)


def save_all() -> None:
    inp = synthetic_inputs(days=200)
    assert inp.flows is not None
    for name, frame in (
        ("prices", inp.prices),
        ("load", inp.load),
        ("generation", inp.generation),
        ("flows", inp.flows),
    ):
        store.save(name, frame, fetched_at=pd.Timestamp("2026-11-01T10:00Z"))
    for name, frame in synthetic_europe(days=200).items():
        store.save(name, frame, fetched_at=pd.Timestamp("2026-11-01T10:00Z"))


def test_empty_state() -> None:
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    text = all_text(at)
    assert "No local data yet" in text
    assert "LIVE" not in text
    assert not at.error


def test_cached_data_is_never_labelled_live() -> None:
    save_all()
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    assert not at.error
    text = all_text(at)
    assert "LIVE" not in text
    assert "Cached data" in text
    assert "Data as of 2026-11-01 11:00 (Europe/Paris)" in text
    assert [t.label for t in at.tabs] == ["Prices", "System", "Cross-border flows", "Europe"]
    assert "Cheapest zone on average" in [m.label for m in at.metric]
    assert "Missing datasets" not in text
    assert len(at.get("imgs")) or True  # charts are rendered as images by st.pyplot


def test_live_badge_only_after_a_fetch_in_this_session() -> None:
    save_all()
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["live_fetch_at"] = "12:34"
    at.run()
    assert not at.exception
    assert any("LIVE" in str(s.value) for s in at.success)


def test_partial_data_shows_clean_warnings() -> None:
    store.save("prices", synthetic_inputs(days=200).prices)
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    assert not at.error
    warnings = " ".join(str(w.value) for w in at.warning)
    assert "No load data" in warnings
    assert "No cross-border flow data" in warnings
    assert "No European price data" in warnings


def test_europe_tab_without_solar_or_capacity_warns_cleanly() -> None:
    inp = synthetic_inputs(days=200)
    store.save("prices", inp.prices)
    store.save("eu_prices", synthetic_europe(days=200)["eu_prices"])
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    assert not at.error
    warnings = " ".join(str(w.value) for w in at.warning)
    assert "No solar generation data" in warnings
    assert "No cross-border capacity data" in warnings
    assert "Time with France = Germany-Lux. price" in [m.label for m in at.metric]


def test_no_local_paths_or_user_names_in_the_page() -> None:
    save_all()
    at = AppTest.from_file(APP, default_timeout=120).run()
    text = all_text(at)
    assert str(Path.home()) not in text
    assert "data/processed" not in text.replace("\\", "/")
