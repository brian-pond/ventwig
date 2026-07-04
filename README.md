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
local_path    = "vendor/appkit"
upstream      = "https://github.com/you/appkit.git"
upstream_path = "src/appkit"    # optional — defaults to repo root
ref           = "main"          # branch name or tag
```

Multiple `[[tool.ventwig.sources]]` entries are allowed. ventwig requires the consuming project to be inside a git working tree.

## Use

```
ventwig sync              # sync all configured sources
ventwig sync appkit       # sync one source by name
ventwig sync --dry-run    # preview changes without writing anything
ventwig sync --force      # overwrite even if local content has drifted

ventwig status            # show sync state for all sources
ventwig status appkit     # show sync state for one source
```

After a successful sync, ventwig writes `.ventwig.lock` alongside your `pyproject.toml`. Commit it — it records the synced commit hash and a content tree hash used for drift detection on the next sync.

## What it is not

- Not a package manager. It vendors files, not installed packages.
- Not bidirectional. Edits always happen upstream; ventwig only pulls.
- Not `git subtree` or `git submodule`. The vendored directory is plain tracked content with no git history coupling.
