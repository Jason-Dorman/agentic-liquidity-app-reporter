"""Paths by date; save and load the data pack, derived.json, reports, and the watch list."""

import json
import re
import shutil
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

    def failure_file(self, name: str) -> Path:
        return self.failures / f"{name}.json"


def pack_paths(root: Path, run_date: date) -> PackPaths:
    """The pack for `run_date` under `root`, the directory that holds data/ (T-28)."""
    return PackPaths(root / "data" / run_date.isoformat())


def write_json(path: Path, value: object) -> None:
    """Sorted keys, two-space indent, a final newline (DATA-CONTRACTS conventions)."""
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", "utf-8")


def _check_names(*groups: Mapping[str, object]) -> None:
    bad = [name for group in groups for name in group if not _NAME.fullmatch(name)]
    if bad:
        raise ValueError(f"not a plain catalogue name: {bad!r}")


def _clear(paths: PackPaths) -> None:
    """Remove an earlier pull of this date, so the pack is exactly one pull (T-30)."""
    for directory in (paths.raw, paths.failures):
        if directory.exists():
            shutil.rmtree(directory)
    paths.manifest.unlink(missing_ok=True)


def save_pack(
    paths: PackPaths,
    raw: Mapping[str, bytes],
    failures: Mapping[str, Mapping],
    manifest: Mapping,
) -> None:
    """Write one pull: raw bodies byte for byte (R-PULL-2), failure records, the manifest.

    An earlier pull of the same date is removed first (T-30); derived.json is left alone.
    """
    _check_names(raw, failures)
    _clear(paths)
    paths.raw.mkdir(parents=True)
    for name, body in raw.items():
        paths.raw_file(name).write_bytes(body)
    if failures:
        paths.failures.mkdir()
        for name, record in failures.items():
            write_json(paths.failure_file(name), record)
    write_json(paths.manifest, manifest)
