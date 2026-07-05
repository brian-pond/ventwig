# ventwig

Vendors source directories from a git repository into your project — as plain files, not as a submodule or package dependency.

## Problem

If you maintain several small CLI tools that share configuration and logging boilerplate, the options are:

- Add a runtime PyPI dependency on that boilerplate — which anyone forking the tool has to explain
- Copy the files by hand — which drifts

ventwig is a third option: a dev-time tool that clones a canonical upstream repo, copies a designated subdirectory into your project tree, and tracks a content hash so it can detect if the local copy has been hand-edited since the last sync.

## Install

```
pip install ventwig
```

ventwig is a dev-time tool. Do not list it in `[project.dependencies]`.

## Configure

In your project's `pyproject.toml`:

```toml
[[tool.ventwig.sources]]
name          = "appkit"
local_path    = "src/mypackage/_vendor/appkit"
upstream      = "https://github.com/you/appkit.git"
upstream_path = "src/appkit"    # optional — defaults to repo root
ref           = "main"          # branch name or tag
```

Multiple `[[tool.ventwig.sources]]` entries are allowed. ventwig requires the consuming project to be inside a git working tree.

### Global options

These keys live in `[tool.ventwig]` (not inside a source block):

```toml
[tool.ventwig]
create_parent_package_markers = true   # default; see below
```

## Use

```
ventwig sync              # sync all configured sources
ventwig sync appkit       # sync one source by name
ventwig sync --dry-run    # preview changes without writing anything
ventwig sync --force      # overwrite even if local content has drifted
ventwig sync --add-runtime-dependencies   # also add missing upstream deps (see below)

ventwig status            # show sync state for all sources
ventwig status appkit     # show sync state for one source
```

After a successful sync, ventwig writes `.ventwig.lock` alongside your `pyproject.toml`. Commit it — it records the synced commit hash and a content tree hash used for drift detection on the next sync.

## Package discovery and `__init__.py` markers

When vendoring into a `src/` layout project that uses setuptools' normal package discovery, every intermediate directory in the vendored path must be a Python package (i.e., contain `__init__.py`). For example, given:

```toml
local_path = "src/mypackage/_vendor/appkit"
```

After sync, `src/mypackage/_vendor/appkit/__init__.py` exists (it came from upstream), but `src/mypackage/_vendor/__init__.py` does not — which causes setuptools to silently skip the vendored code during `pip install`.

By default, ventwig creates any missing `__init__.py` files in parent directories, walking up from `local_path` until it reaches a directory that already has one. To disable this behavior:

```toml
[tool.ventwig]
create_parent_package_markers = false
```

## Runtime dependency checking

When syncing, ventwig reads the upstream package's `[project.dependencies]` and compares them against the downstream project's declared dependencies. Any upstream runtime dependency that is absent downstream is reported as a warning:

```
Warning: upstream runtime deps missing from downstream project:
  - structlog>=21.0
Tip: re-run with --add-runtime-dependencies to add them automatically.
```

To have ventwig add the missing dependencies directly to your `pyproject.toml`:

```
ventwig sync --add-runtime-dependencies
```

This uses `tomlkit` to edit the file in place, so comments and formatting are preserved. Dependency version specifiers are copied verbatim from upstream; review them before committing. If the upstream has no `pyproject.toml` or declares no runtime dependencies, this step is silently skipped.

## What it is not

- Not a package manager. It vendors files, not installed packages.
- Not bidirectional. Edits always happen upstream; ventwig only pulls.
- Not `git subtree` or `git submodule`. The vendored directory is plain tracked content with no git history coupling.
