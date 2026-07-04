from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

from ventwig.errors import DriftError, PreconditionError, VentwigError
from ventwig.sync import run_status, run_sync

# ---------------------------------------------------------------------------
# M1 — basic clone/replace
# ---------------------------------------------------------------------------

def test_sync_full_repo(tmp_path: Path, git_repo_factory, git_consumer_factory) -> None:
    upstream = git_repo_factory("upstream", {
        "hello.py": "print('hello')",
        "world.py": "print('world')",
    })
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    run_sync(start=consumer)
    assert (consumer / "vendor" / "mylib" / "hello.py").read_text() == "print('hello')"
    assert (consumer / "vendor" / "mylib" / "world.py").read_text() == "print('world')"


def test_sync_with_upstream_path(tmp_path: Path, git_repo_factory, git_consumer_factory) -> None:
    upstream = git_repo_factory("upstream", {
        "src/mylib/foo.py": "x = 1",
        "src/mylib/bar.py": "y = 2",
        "README.md": "# not vendored",
        "setup.py": "# also not vendored",
    })
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
upstream_path = "src/mylib"
ref = "main"
""")
    run_sync(start=consumer)
    vendor = consumer / "vendor" / "mylib"
    assert (vendor / "foo.py").read_text() == "x = 1"
    assert (vendor / "bar.py").read_text() == "y = 2"
    assert not (vendor / "README.md").exists()
    assert not (vendor / "setup.py").exists()


def test_sync_replaces_existing_contents(
    tmp_path: Path, git_repo_factory, git_consumer_factory
) -> None:
    upstream = git_repo_factory("upstream", {"new.py": "new = True"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    stale = consumer / "vendor" / "mylib"
    stale.mkdir(parents=True)
    (stale / "old.py").write_text("old = True")

    run_sync(start=consumer)
    assert (stale / "new.py").read_text() == "new = True"
    assert not (stale / "old.py").exists()


def test_sync_no_dot_git_vendored(
    tmp_path: Path, git_repo_factory, git_consumer_factory
) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    run_sync(start=consumer)
    assert not (consumer / "vendor" / "mylib" / ".git").exists()


def test_sync_single_source_by_name(
    tmp_path: Path, git_repo_factory, git_consumer_factory
) -> None:
    upstream_a = git_repo_factory("upstream_a", {"a.py": "a = 1"})
    upstream_b = git_repo_factory("upstream_b", {"b.py": "b = 2"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "lib_a"
local_path = "vendor/lib_a"
upstream = "{upstream_a}"
ref = "main"

[[tool.ventwig.sources]]
name = "lib_b"
local_path = "vendor/lib_b"
upstream = "{upstream_b}"
ref = "main"
""")
    run_sync(source_name="lib_a", start=consumer)
    assert (consumer / "vendor" / "lib_a" / "a.py").exists()
    assert not (consumer / "vendor" / "lib_b").exists()


def test_sync_unknown_source_name_raises(
    tmp_path: Path, git_repo_factory, git_consumer_factory
) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    with pytest.raises(VentwigError, match="No source named"):
        run_sync(source_name="nonexistent", start=consumer)


def test_sync_invalid_upstream_path_raises(
    tmp_path: Path, git_repo_factory, git_consumer_factory
) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
upstream_path = "nonexistent/subdir"
ref = "main"
""")
    with pytest.raises(VentwigError, match="not found in cloned repo"):
        run_sync(start=consumer)


def test_sync_dry_run_writes_nothing(
    tmp_path: Path, git_repo_factory, git_consumer_factory
) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    run_sync(dry_run=True, start=consumer)
    assert not (consumer / "vendor" / "mylib").exists()


# ---------------------------------------------------------------------------
# M2 — drift detection and lock file
# ---------------------------------------------------------------------------

def test_sync_writes_lock_file(tmp_path: Path, git_repo_factory, git_consumer_factory) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    run_sync(start=consumer)
    lock_file = consumer / ".ventwig.lock"
    assert lock_file.exists()
    with lock_file.open("rb") as f:
        data = tomllib.load(f)
    assert "mylib" in data
    assert len(data["mylib"]["synced_commit"]) == 40
    assert len(data["mylib"]["synced_tree"]) == 40
    assert "synced_at" in data["mylib"]


def test_sync_lock_records_upstream_path(
    tmp_path: Path, git_repo_factory, git_consumer_factory
) -> None:
    upstream = git_repo_factory("upstream", {"src/mylib/foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
upstream_path = "src/mylib"
ref = "main"
""")
    run_sync(start=consumer)
    with (consumer / ".ventwig.lock").open("rb") as f:
        data = tomllib.load(f)
    assert data["mylib"]["upstream_path"] == "src/mylib"


def test_resync_without_changes_passes(
    tmp_path: Path, git_repo_factory, git_consumer_factory
) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    run_sync(start=consumer)
    run_sync(start=consumer)  # second sync must not raise


def test_drift_detected_raises(tmp_path: Path, git_repo_factory, git_consumer_factory) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    run_sync(start=consumer)
    (consumer / "vendor" / "mylib" / "foo.py").write_text("x = HAND_EDITED")
    with pytest.raises(DriftError, match="drifted"):
        run_sync(start=consumer)


def test_drift_force_proceeds_and_restores(
    tmp_path: Path, git_repo_factory, git_consumer_factory
) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    run_sync(start=consumer)
    (consumer / "vendor" / "mylib" / "foo.py").write_text("x = HAND_EDITED")
    run_sync(force=True, start=consumer)
    assert (consumer / "vendor" / "mylib" / "foo.py").read_text() == "x = 1"


def test_no_lock_entry_skips_drift_check(
    tmp_path: Path, git_repo_factory, git_consumer_factory
) -> None:
    """local_path exists but no lock entry — no baseline, so sync proceeds."""
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    (consumer / "vendor" / "mylib").mkdir(parents=True)
    (consumer / "vendor" / "mylib" / "manual.py").write_text("manual = True")
    run_sync(start=consumer)  # must not raise
    assert (consumer / "vendor" / "mylib" / "foo.py").exists()


# ---------------------------------------------------------------------------
# M3 — git precondition and porcelain check
# ---------------------------------------------------------------------------

def test_precondition_fails_outside_git(tmp_path: Path, git_repo_factory) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = tmp_path / "no_git_consumer"
    consumer.mkdir()
    (consumer / "pyproject.toml").write_text(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    with pytest.raises(PreconditionError, match="git working tree"):
        run_sync(start=consumer)


def test_porcelain_check_detects_uncommitted_tracked_changes(
    tmp_path: Path, git_repo_factory, git_consumer_factory
) -> None:
    """Porcelain check catches a staged-but-not-committed change that the drift check would miss.

    Scenario: stage a modification, then restore the working tree to match the last sync tree.
    The tree hash equals the lock (no drift), but git's index differs from HEAD — exactly the
    edge case the porcelain check exists to catch.
    """
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    run_sync(start=consumer)

    # Track and commit the vendored directory
    subprocess.run(["git", "add", "vendor/"], check=True, capture_output=True, cwd=consumer)
    subprocess.run(
        ["git", "commit", "-m", "track vendor"],
        check=True, capture_output=True, cwd=consumer,
    )

    # Stage a change to the index …
    (consumer / "vendor" / "mylib" / "foo.py").write_text("x = STAGED_CHANGE")
    subprocess.run(
        ["git", "add", "vendor/mylib/foo.py"], check=True, capture_output=True, cwd=consumer
    )
    # … then restore the working tree to the original content.
    # Now: working-tree hash == lock's synced_tree (drift check passes),
    # but the git index still differs from HEAD (porcelain check fires).
    (consumer / "vendor" / "mylib" / "foo.py").write_text("x = 1")

    with pytest.raises(DriftError, match="uncommitted changes"):
        run_sync(start=consumer)


def test_porcelain_check_skipped_with_force(
    tmp_path: Path, git_repo_factory, git_consumer_factory
) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    run_sync(start=consumer)
    subprocess.run(["git", "add", "vendor/"], check=True, capture_output=True, cwd=consumer)
    subprocess.run(
        ["git", "commit", "-m", "track vendor"],
        check=True, capture_output=True, cwd=consumer,
    )
    (consumer / "vendor" / "mylib" / "foo.py").write_text("x = MODIFIED")

    run_sync(force=True, start=consumer)
    assert (consumer / "vendor" / "mylib" / "foo.py").read_text() == "x = 1"


def test_porcelain_check_ignores_untracked(
    tmp_path: Path, git_repo_factory, git_consumer_factory
) -> None:
    """Untracked vendored files (never git-added) must not trigger the porcelain check."""
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    run_sync(start=consumer)
    # vendor/mylib is untracked at this point — second sync must still pass
    run_sync(start=consumer)


# ---------------------------------------------------------------------------
# M4 — ventwig status
# ---------------------------------------------------------------------------

def test_status_clean_after_sync(
    tmp_path: Path, git_repo_factory, git_consumer_factory, capsys
) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    run_sync(start=consumer)
    all_clean = run_status(start=consumer)
    assert all_clean
    out = capsys.readouterr().out
    assert "ok" in out
    assert "clean" in out
    assert "mylib" in out


def test_status_not_synced(
    tmp_path: Path, git_repo_factory, git_consumer_factory, capsys
) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    all_clean = run_status(start=consumer)
    assert not all_clean
    out = capsys.readouterr().out
    assert "not synced" in out


def test_status_drifted(
    tmp_path: Path, git_repo_factory, git_consumer_factory, capsys
) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    run_sync(start=consumer)
    (consumer / "vendor" / "mylib" / "foo.py").write_text("x = HAND_EDITED")

    all_clean = run_status(start=consumer)
    assert not all_clean
    out = capsys.readouterr().out
    assert "drifted" in out
    assert "!!" in out


def test_status_untracked(
    tmp_path: Path, git_repo_factory, git_consumer_factory, capsys
) -> None:
    """local_path exists but no lock entry → untracked."""
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    (consumer / "vendor" / "mylib").mkdir(parents=True)
    (consumer / "vendor" / "mylib" / "manual.py").write_text("manual = True")

    all_clean = run_status(start=consumer)
    assert not all_clean
    out = capsys.readouterr().out
    assert "untracked" in out


def test_status_staged(
    tmp_path: Path, git_repo_factory, git_consumer_factory, capsys
) -> None:
    """Staged-but-restored scenario: tree hash matches lock, git index differs from HEAD."""
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    run_sync(start=consumer)
    subprocess.run(["git", "add", "vendor/"], check=True, capture_output=True, cwd=consumer)
    subprocess.run(
        ["git", "commit", "-m", "track vendor"], check=True, capture_output=True, cwd=consumer
    )
    (consumer / "vendor" / "mylib" / "foo.py").write_text("x = STAGED")
    subprocess.run(
        ["git", "add", "vendor/mylib/foo.py"], check=True, capture_output=True, cwd=consumer
    )
    (consumer / "vendor" / "mylib" / "foo.py").write_text("x = 1")  # restore working tree

    all_clean = run_status(start=consumer)
    assert not all_clean
    out = capsys.readouterr().out
    assert "staged" in out
    assert "!!" in out


def test_status_single_source_by_name(
    tmp_path: Path, git_repo_factory, git_consumer_factory, capsys
) -> None:
    upstream_a = git_repo_factory("upstream_a", {"a.py": "a = 1"})
    upstream_b = git_repo_factory("upstream_b", {"b.py": "b = 2"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "lib_a"
local_path = "vendor/lib_a"
upstream = "{upstream_a}"
ref = "main"

[[tool.ventwig.sources]]
name = "lib_b"
local_path = "vendor/lib_b"
upstream = "{upstream_b}"
ref = "main"
""")
    run_sync(start=consumer)
    capsys.readouterr()  # drain sync output before asserting on status
    run_status(source_name="lib_a", start=consumer)
    out = capsys.readouterr().out
    assert "lib_a" in out
    assert "lib_b" not in out


def test_status_unknown_source_name_raises(
    tmp_path: Path, git_repo_factory, git_consumer_factory
) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    consumer = git_consumer_factory(f"""
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "{upstream}"
ref = "main"
""")
    with pytest.raises(VentwigError, match="No source named"):
        run_status(source_name="nonexistent", start=consumer)
