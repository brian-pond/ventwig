from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .errors import GitError, PreconditionError


def _run(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(args, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        cmd = " ".join(args)
        raise GitError(f"`{cmd}` failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def find_git_root(start: Path) -> Path:
    """Return the git working tree root for start, or raise PreconditionError."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, cwd=start,
    )
    if result.returncode != 0:
        raise PreconditionError(
            "ventwig must be run inside a git working tree. "
            "Initialize one with `git init` before using ventwig."
        )
    return Path(result.stdout.strip())


def has_uncommitted_changes(repo_root: Path, local_path: Path) -> bool:
    """Return True if git sees staged or unstaged changes to tracked files under local_path.

    Untracked (??) entries are excluded — only changes to already-tracked content count.
    Returns False when local_path is outside repo_root.
    """
    try:
        rel = local_path.relative_to(repo_root)
    except ValueError:
        return False

    result = subprocess.run(
        ["git", "status", "--porcelain", "--", str(rel)],
        capture_output=True, text=True, cwd=repo_root,
    )
    if result.returncode != 0:
        raise GitError(f"git status failed:\n{result.stderr.strip()}")

    tracked_changes = [line for line in result.stdout.splitlines() if not line.startswith("??")]
    return bool(tracked_changes)


def clone(upstream: str, ref: str, dest: Path) -> str:
    """Shallow-clone upstream at ref into dest. Returns the resolved commit hash."""
    _run(["git", "clone", "--depth", "1", "--branch", ref, upstream, str(dest)])
    return _run(["git", "rev-parse", "HEAD"], cwd=dest)


def compute_tree_hash(local_path: Path) -> str:
    """Return the git tree hash of local_path's contents.

    Uses a scratch git repo so the consuming project's index is never touched.
    Two directories with identical file paths and contents will produce the same hash.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        _run(["git", "init", "-q", str(repo)])
        shutil.copytree(
            local_path, repo, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git")
        )
        _run(["git", "-C", str(repo), "add", "-A"])
        return _run(["git", "-C", str(repo), "write-tree"])
