from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from ventwig.errors import LockError
from ventwig.lock import read_lock, update_lock_entry, write_lock


def _pyproject(tmp_path: Path) -> Path:
    p = tmp_path / "pyproject.toml"
    p.write_text("")
    return p


def test_read_nonexistent_lock_returns_empty(tmp_path: Path) -> None:
    pyproject = _pyproject(tmp_path)
    assert read_lock(pyproject) == {}


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    pyproject = _pyproject(tmp_path)
    data: dict = {
        "mylib": {
            "synced_commit": "abc123",
            "synced_tree": "def456",
            "synced_at": "2026-07-04T12:00:00Z",
        }
    }
    write_lock(pyproject, data)
    assert read_lock(pyproject) == data


def test_lock_file_is_valid_toml(tmp_path: Path) -> None:
    pyproject = _pyproject(tmp_path)
    update_lock_entry(pyproject, "mylib", "abc123", "def456", None)
    lock_file = tmp_path / ".ventwig.lock"
    with lock_file.open("rb") as f:
        tomllib.load(f)  # must not raise


def test_update_creates_entry(tmp_path: Path) -> None:
    pyproject = _pyproject(tmp_path)
    update_lock_entry(pyproject, "mylib", "abc123", "def456", None)
    data = read_lock(pyproject)
    assert data["mylib"]["synced_commit"] == "abc123"
    assert data["mylib"]["synced_tree"] == "def456"
    assert "synced_at" in data["mylib"]


def test_update_omits_upstream_path_when_none(tmp_path: Path) -> None:
    pyproject = _pyproject(tmp_path)
    update_lock_entry(pyproject, "mylib", "abc123", "def456", None)
    data = read_lock(pyproject)
    assert "upstream_path" not in data["mylib"]


def test_update_records_upstream_path_when_set(tmp_path: Path) -> None:
    pyproject = _pyproject(tmp_path)
    update_lock_entry(pyproject, "mylib", "abc123", "def456", "src/mylib")
    data = read_lock(pyproject)
    assert data["mylib"]["upstream_path"] == "src/mylib"


def test_update_overwrites_existing_entry(tmp_path: Path) -> None:
    pyproject = _pyproject(tmp_path)
    update_lock_entry(pyproject, "mylib", "old_commit", "old_tree", None)
    update_lock_entry(pyproject, "mylib", "new_commit", "new_tree", None)
    data = read_lock(pyproject)
    assert data["mylib"]["synced_commit"] == "new_commit"
    assert data["mylib"]["synced_tree"] == "new_tree"


def test_update_preserves_other_sources(tmp_path: Path) -> None:
    pyproject = _pyproject(tmp_path)
    update_lock_entry(pyproject, "lib_a", "aaa", "aaa_tree", None)
    update_lock_entry(pyproject, "lib_b", "bbb", "bbb_tree", None)
    data = read_lock(pyproject)
    assert "lib_a" in data
    assert "lib_b" in data


def test_corrupt_lock_raises(tmp_path: Path) -> None:
    pyproject = _pyproject(tmp_path)
    (tmp_path / ".ventwig.lock").write_bytes(b"not valid toml ][[[")
    with pytest.raises(LockError, match="Failed to read"):
        read_lock(pyproject)
