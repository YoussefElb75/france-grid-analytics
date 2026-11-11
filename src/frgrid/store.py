"""Local storage of processed datasets as Parquet in the git-ignored data folder.

Each dataset ``<name>.parquet`` has a sidecar ``<name>.meta.json`` recording when it was fetched
from ENTSO-E (UTC) and the requested period, so that the dashboard can state how fresh it is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from frgrid.settings import data_dir


@dataclass(frozen=True)
class Meta:
    fetched_at: pd.Timestamp  # UTC
    start: pd.Timestamp | None  # requested period, UTC
    end: pd.Timestamp | None


def processed_dir() -> Path:
    return data_dir() / "processed"


def cache_dir() -> Path:
    return data_dir() / "cache"


def path_for(name: str) -> Path:
    return processed_dir() / f"{name}.parquet"


def meta_path_for(name: str) -> Path:
    return processed_dir() / f"{name}.meta.json"


def save(
    name: str,
    frame: pd.DataFrame,
    *,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    fetched_at: pd.Timestamp | None = None,
) -> Path:
    path = path_for(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    stamp = fetched_at if fetched_at is not None else pd.Timestamp.now(tz="UTC")
    meta = {
        "fetched_at": stamp.tz_convert("UTC").isoformat(),
        "start": None if start is None else start.tz_convert("UTC").isoformat(),
        "end": None if end is None else end.tz_convert("UTC").isoformat(),
    }
    meta_path_for(name).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return path


def exists(name: str) -> bool:
    return path_for(name).is_file()


def load(name: str) -> pd.DataFrame:
    path = path_for(name)
    if not path.is_file():
        msg = f"dataset '{name}' not found; run `frgrid fetch` first"
        raise FileNotFoundError(msg)
    return pd.read_parquet(path)


def read_meta(name: str) -> Meta | None:
    """Fetch metadata; falls back to the Parquet file's modification time if no sidecar exists."""
    path = path_for(name)
    if not path.is_file():
        return None
    meta_file = meta_path_for(name)
    if meta_file.is_file():
        raw = json.loads(meta_file.read_text(encoding="utf-8"))
        return Meta(
            fetched_at=pd.Timestamp(raw["fetched_at"]).tz_convert("UTC"),
            start=pd.Timestamp(raw["start"]) if raw.get("start") else None,
            end=pd.Timestamp(raw["end"]) if raw.get("end") else None,
        )
    mtime = pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC")
    return Meta(fetched_at=mtime, start=None, end=None)
