from __future__ import annotations

import re
import shutil
import tempfile
import tomllib
from enum import Enum
from pathlib import Path

import tomlkit

from .config import SourceConfig, VentwigGlobalConfig, load_sources
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
    pyproject_path, _global_config, sources = load_sources(start)
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
# Parent package marker helpers
# ---------------------------------------------------------------------------

def _create_parent_markers(local_path: Path, project_root: Path, *, dry_run: bool) -> list[Path]:
    """Walk up from local_path.parent creating __init__.py in dirs that lack one.

    Stops when an existing __init__.py is found or when reaching project_root.
    Returns the list of paths created (or that would be created in dry_run).
    """
    touched: list[Path] = []
    current = local_path.parent
    while current != project_root:
        try:
            current.relative_to(project_root)
        except ValueError:
            break
        marker = current / "__init__.py"
        if marker.exists():
            break
        if not dry_run:
            marker.touch()
        touched.append(marker)
        current = current.parent
    return touched


# ---------------------------------------------------------------------------
# Runtime dependency helpers
# ---------------------------------------------------------------------------

def _normalize_dep_name(specifier: str) -> str:
    """Extract the normalized package name from a PEP 508 dependency specifier."""
    name = re.split(r"[>=<!;\[\s]", specifier)[0].strip()
    return name.lower().replace("-", "_")


def _check_runtime_deps(clone_dir: Path, pyproject_path: Path) -> list[str]:
    """Return upstream runtime deps that are absent from the downstream project.

    Reads [project.dependencies] from both the cloned upstream repo and the
    downstream pyproject.toml and returns the subset that is missing downstream.
    Returns an empty list when the upstream has no pyproject.toml or no dependencies.
    """
    upstream_pyproject = clone_dir / "pyproject.toml"
    if not upstream_pyproject.exists():
        return []

    with upstream_pyproject.open("rb") as f:
        upstream_data = tomllib.load(f)
    upstream_deps: list[str] = upstream_data.get("project", {}).get("dependencies", [])
    if not upstream_deps:
        return []

    with pyproject_path.open("rb") as f:
        downstream_data = tomllib.load(f)
    downstream_deps: list[str] = downstream_data.get("project", {}).get("dependencies", [])
    downstream_names = {_normalize_dep_name(d) for d in downstream_deps}

    return [dep for dep in upstream_deps if _normalize_dep_name(dep) not in downstream_names]


def _add_deps_to_pyproject(pyproject_path: Path, deps: list[str]) -> None:
    """Append deps to [project.dependencies] in pyproject.toml, preserving formatting."""
    with pyproject_path.open("r", encoding="utf-8") as f:
        doc = tomlkit.load(f)

    if "project" not in doc:
        doc.add("project", tomlkit.table())
    project_table = doc["project"]

    if "dependencies" not in project_table:
        project_table.add("dependencies", tomlkit.array())
    deps_array = project_table["dependencies"]

    existing_names = {_normalize_dep_name(d) for d in deps_array}
    added = [dep for dep in deps if _normalize_dep_name(dep) not in existing_names]
    if not added:
        return

    for dep in added:
        deps_array.append(dep)

    tmp = pyproject_path.parent / (pyproject_path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            tomlkit.dump(doc, f)
        tmp.replace(pyproject_path)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise VentwigError(f"Failed to update pyproject.toml: {exc}") from exc

    for dep in added:
        print(f"  Added dependency: {dep}")


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
    source: SourceConfig,
    global_config: VentwigGlobalConfig,
    *,
    dry_run: bool,
    force: bool,
    pyproject_path: Path,
    repo_root: Path,
    add_runtime_deps: bool,
) -> None:
    if source.local_path.exists() and not force:
        _check_local_state(source, pyproject_path, repo_root)

    with tempfile.TemporaryDirectory() as tmpdir:
        clone_dir = Path(tmpdir) / "clone"

        print(f"  Cloning {source.upstream} @ {source.ref} ...")
        commit = clone(source.upstream, source.ref, clone_dir)

        # Dep check while the clone is still on disk.
        missing_deps = _check_runtime_deps(clone_dir, pyproject_path)

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
            if global_config.create_parent_package_markers:
                would_create = _create_parent_markers(
                    source.local_path, pyproject_path.parent, dry_run=True
                )
                for marker in would_create:
                    print(f"  [dry-run] Would create {marker.relative_to(pyproject_path.parent)}")
            if missing_deps:
                print(f"  Warning: upstream runtime deps missing from downstream project:")
                for dep in missing_deps:
                    print(f"    - {dep}")
            return

        if source.local_path.exists():
            shutil.rmtree(source.local_path)

        shutil.copytree(src, source.local_path, ignore=shutil.ignore_patterns(".git"))

    # Parent marker creation (after temp dir is gone — operates on local_path only).
    if global_config.create_parent_package_markers:
        created = _create_parent_markers(
            source.local_path, pyproject_path.parent, dry_run=False
        )
        for marker in created:
            print(f"  Created package marker: {marker.relative_to(pyproject_path.parent)}")

    if missing_deps:
        print(f"  Warning: upstream runtime deps missing from downstream project:")
        for dep in missing_deps:
            print(f"    - {dep}")
        if add_runtime_deps:
            _add_deps_to_pyproject(pyproject_path, missing_deps)
        else:
            print("  Tip: re-run with --add-runtime-dependencies to add them automatically.")

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
    add_runtime_deps: bool = False,
    start: Path | None = None,
) -> None:
    pyproject_path, global_config, sources = load_sources(start)
    repo_root = find_git_root(pyproject_path.parent)

    if source_name:
        sources = [s for s in sources if s.name == source_name]
        if not sources:
            raise VentwigError(f"No source named '{source_name}' in pyproject.toml.")

    for source in sources:
        print(f"\nSyncing '{source.name}' ...")
        _sync_source(
            source,
            global_config,
            dry_run=dry_run,
            force=force,
            pyproject_path=pyproject_path,
            repo_root=repo_root,
            add_runtime_deps=add_runtime_deps,
        )
