from __future__ import annotations

import shutil
import tempfile
from enum import Enum
from pathlib import Path

from .config import SourceConfig, load_sources
from .errors import DriftError, VentwigError
from .git_ops import clone, compute_tree_hash, find_git_root, has_uncommitted_changes
from .lock import read_lock, update_lock_entry

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

class SourceStatus(Enum):
    CLEAN = "clean"
    DRIFTED = "drifted"
    STAGED = "staged changes"
    UNTRACKED = "untracked"
    NOT_SYNCED = "not synced"


def _get_source_status(
    source: SourceConfig, lock_data: dict, repo_root: Path
) -> tuple[SourceStatus, str]:
    """Return (status, detail) for source without raising or modifying anything."""
    if not source.local_path.exists():
        return SourceStatus.NOT_SYNCED, ""

    lock_entry = lock_data.get(source.name)
    if lock_entry is None:
        return SourceStatus.UNTRACKED, ""

    current_tree = compute_tree_hash(source.local_path)
    if current_tree != lock_entry["synced_tree"]:
        detail = f"last sync @ {lock_entry['synced_commit'][:12]}  {lock_entry['synced_at']}"
        return SourceStatus.DRIFTED, detail

    if has_uncommitted_changes(repo_root, source.local_path):
        detail = f"@ {lock_entry['synced_commit'][:12]}  {lock_entry['synced_at']}"
        return SourceStatus.STAGED, detail

    detail = f"@ {lock_entry['synced_commit'][:12]}  {lock_entry['synced_at']}"
    return SourceStatus.CLEAN, detail


_STATUS_INDICATOR = {
    SourceStatus.CLEAN: "ok",
    SourceStatus.DRIFTED: "!!",
    SourceStatus.STAGED: "!!",
    SourceStatus.UNTRACKED: "--",
    SourceStatus.NOT_SYNCED: "--",
}


def run_status(
    source_name: str | None = None,
    *,
    start: Path | None = None,
) -> bool:
    """Print sync status for each source. Returns True only if all sources are clean."""
    pyproject_path, sources = load_sources(start)
    repo_root = find_git_root(pyproject_path.parent)

    if source_name:
        sources = [s for s in sources if s.name == source_name]
        if not sources:
            raise VentwigError(f"No source named '{source_name}' in pyproject.toml.")

    lock_data = read_lock(pyproject_path)
    name_width = max(len(s.name) for s in sources)
    status_width = max(len(st.value) for st in SourceStatus)

    all_clean = True
    for source in sources:
        st, detail = _get_source_status(source, lock_data, repo_root)
        if st != SourceStatus.CLEAN:
            all_clean = False
        indicator = _STATUS_INDICATOR[st]
        line = f"  [{indicator}]  {source.name:<{name_width}}  {st.value:<{status_width}}"
        if detail:
            line += f"  {detail}"
        print(line.rstrip())

    return all_clean


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def _check_local_state(source: SourceConfig, pyproject_path: Path, repo_root: Path) -> None:
    """Run drift and porcelain checks. Raises DriftError if either fails."""
    lock_entry = read_lock(pyproject_path).get(source.name)
    if lock_entry:
        print("  Checking for drift ...")
        current_tree = compute_tree_hash(source.local_path)
        if current_tree != lock_entry["synced_tree"]:
            raise DriftError(
                f"'{source.name}' has drifted from the last sync "
                f"(tree {lock_entry['synced_tree'][:12]} → {current_tree[:12]}). "
                f"Looks like a hand-edit. Re-run with --force to overwrite anyway."
            )

    if has_uncommitted_changes(repo_root, source.local_path):
        raise DriftError(
            f"'{source.name}': git reports uncommitted changes under {source.local_path}. "
            f"Commit or stash those changes first, or re-run with --force."
        )


def _sync_source(
    source: SourceConfig, *, dry_run: bool, force: bool, pyproject_path: Path, repo_root: Path
) -> None:
    if source.local_path.exists() and not force:
        _check_local_state(source, pyproject_path, repo_root)

    with tempfile.TemporaryDirectory() as tmpdir:
        clone_dir = Path(tmpdir) / "clone"

        print(f"  Cloning {source.upstream} @ {source.ref} ...")
        commit = clone(source.upstream, source.ref, clone_dir)

        if source.upstream_path:
            src = clone_dir / source.upstream_path
            if not src.is_dir():
                raise VentwigError(
                    f"upstream_path '{source.upstream_path}' not found in cloned repo."
                )
        else:
            src = clone_dir

        if dry_run:
            print(f"  [dry-run] Would replace {source.local_path} from commit {commit[:12]}")
            return

        if source.local_path.exists():
            shutil.rmtree(source.local_path)

        shutil.copytree(src, source.local_path, ignore=shutil.ignore_patterns(".git"))

        tree_hash = compute_tree_hash(source.local_path)
        update_lock_entry(
            pyproject_path,
            source.name,
            synced_commit=commit,
            synced_tree=tree_hash,
            upstream_path=source.upstream_path,
        )

        print(f"  Synced '{source.name}' @ {commit[:12]}")


def run_sync(
    source_name: str | None = None,
    *,
    dry_run: bool = False,
    force: bool = False,
    start: Path | None = None,
) -> None:
    pyproject_path, sources = load_sources(start)
    repo_root = find_git_root(pyproject_path.parent)

    if source_name:
        sources = [s for s in sources if s.name == source_name]
        if not sources:
            raise VentwigError(f"No source named '{source_name}' in pyproject.toml.")

    for source in sources:
        print(f"\nSyncing '{source.name}' ...")
        _sync_source(
            source, dry_run=dry_run, force=force, pyproject_path=pyproject_path, repo_root=repo_root
        )
