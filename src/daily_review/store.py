"""Paths by date; save and load the data pack, derived.json, reports, and the watch list."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# A catalogue name such as "liquidity_USDT" or "flow_history.retry": a plain file name.
_NAME = re.compile(r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*")


@dataclass(frozen=True)
class PackPaths:
    """Where one date's data pack lives: data/YYYY-MM-DD/ (DATA-CONTRACTS section 1)."""

    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def failures(self) -> Path:
        return self.root / "failures"

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def derived(self) -> Path:
        return self.root / "derived.json"

    def raw_file(self, name: str) -> Path:
        return self.raw / f"{name}.json"


def pack_paths(root: Path, run_date: date) -> PackPaths:
    """The pack for `run_date` under `root`, the directory that holds data/ (T-28)."""
    return PackPaths(root / "data" / run_date.isoformat())


def save_pack(paths: PackPaths, raw: Mapping[str, bytes]) -> None:
    """Write each body to raw/<name>.json byte for byte (R-PULL-2). Overwrites that date."""
    bad = [name for name in raw if not _NAME.fullmatch(name)]
    if bad:
        raise ValueError(f"not a plain catalogue name: {bad!r}")
    paths.raw.mkdir(parents=True, exist_ok=True)
    for name, body in raw.items():
        paths.raw_file(name).write_bytes(body)
