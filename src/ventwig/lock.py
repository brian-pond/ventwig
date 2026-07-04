from __future__ import annotations

import datetime
import tomllib
from typing import TYPE_CHECKING

import tomli_w

if TYPE_CHECKING:
    from pathlib import Path

from .errors import LockError

LOCK_FILENAME = ".ventwig.lock"


def _lock_path(pyproject_path: Path) -> Path:
    return pyproject_path.parent / LOCK_FILENAME


def read_lock(pyproject_path: Path) -> dict[str, dict]:
    lock_file = _lock_path(pyproject_path)
    if not lock_file.exists():
        return {}
    try:
        with lock_file.open("rb") as f:
            return tomllib.load(f)
    except Exception as exc:
        raise LockError(f"Failed to read {LOCK_FILENAME}: {exc}") from exc


def write_lock(pyproject_path: Path, data: dict[str, dict]) -> None:
    lock_file = _lock_path(pyproject_path)
    tmp_file = lock_file.parent / (lock_file.name + ".tmp")
    try:
        with tmp_file.open("wb") as f:
            tomli_w.dump(data, f)
        tmp_file.replace(lock_file)
    except Exception as exc:
        tmp_file.unlink(missing_ok=True)
        raise LockError(f"Failed to write {LOCK_FILENAME}: {exc}") from exc


def update_lock_entry(
    pyproject_path: Path,
    name: str,
    synced_commit: str,
    synced_tree: str,
    upstream_path: str | None,
) -> None:
    data = read_lock(pyproject_path)
    entry: dict = {
        "synced_commit": synced_commit,
        "synced_tree": synced_tree,
        "synced_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if upstream_path is not None:
        entry["upstream_path"] = upstream_path
    data[name] = entry
    write_lock(pyproject_path, data)
