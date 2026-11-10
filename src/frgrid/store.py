"""Local storage of processed datasets as Parquet in the git-ignored data folder."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from frgrid.settings import data_dir


def processed_dir() -> Path:
    return data_dir() / "processed"


def cache_dir() -> Path:
    return data_dir() / "cache"


def path_for(name: str) -> Path:
    return processed_dir() / f"{name}.parquet"


def save(name: str, frame: pd.DataFrame) -> Path:
    path = path_for(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    return path


def load(name: str) -> pd.DataFrame:
    path = path_for(name)
    if not path.is_file():
        msg = f"{path} not found; run `frgrid fetch` first"
        raise FileNotFoundError(msg)
    return pd.read_parquet(path)
