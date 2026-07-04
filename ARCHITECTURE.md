# ventwig — Architecture Reference

This document captures resolved design and implementation decisions. It is the authoritative technical reference for implementation. For the problem statement, rationale, and milestone plan, see `ventwig-project-plan.md`.

---

## Python Version

**Minimum: 3.11.** `tomllib` is available in the stdlib from 3.11. No 3.12-specific features are used; nothing in the implementation warrants raising the floor.

---

## Project Layout

src layout. Prevents accidental `import ventwig` from the project root during development, forcing the installed package to be exercised by tests — important for a PyPI-published tool.

```
ventwig/
├── src/
│   └── ventwig/
│       ├── __init__.py
│       ├── __main__.py      # enables `python -m ventwig`
│       ├── cli.py           # typer app, command definitions, --help strings
│       ├── config.py        # pyproject.toml parsing, SourceConfig model
│       ├── lock.py          # .ventwig.lock read/write
│       ├── git_ops.py       # all subprocess git calls, isolated
│       ├── sync.py          # sync algorithm orchestration
│       └── errors.py        # VentwigError exception hierarchy
├── tests/
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_lock.py
│   │   └── test_git_ops.py
│   └── integration/
│       └── test_sync.py
├── pyproject.toml
└── .ruff.toml               # or inline under [tool.ruff] in pyproject.toml
```

---

## Dependencies

### Runtime

| Package | Purpose |
|---|---|
| `typer` | CLI framework (brings `click` and `rich`) |
| `tomli-w` | `.ventwig.lock` writing — stdlib `tomllib` is intentionally read-only |

### Dev / Build

| Package | Purpose |
|---|---|
| `ruff` | Lint and format |
| `pytest` | Test runner |

**Note on the TOML ecosystem:** The original `toml` PyPI package is unmaintained (last release 2020) and has known spec compliance gaps. The current standard for Python 3.11+ projects is `tomllib` (stdlib, read) + `tomli-w` (PyPI, write). `tomlkit` is an alternative that preserves comments and formatting — useful for round-tripping human-authored TOML, but unnecessary here since `.ventwig.lock` is a generated file.

---

## Configuration Format

Defined in `pyproject.toml` of each **consuming project** — not ventwig itself.

```toml
[[tool.ventwig.sources]]
name          = "datahenge_appkit"
local_path    = "vendor/datahenge_appkit"
upstream      = "https://github.com/<owner>/datahenge-appkit.git"
upstream_path = "src/datahenge_appkit"    # optional; omit to vendor the full repo root
ref           = "main"                     # branch name or tag; commit SHAs not supported
```

- `upstream_path` is **optional**. When absent, the entire cloned repo root is vendored into `local_path`. When present, only the specified subdirectory is copied — this handles `src/` layout upstreams, which are common enough to be a first-class concern.
- Multiple `[[tool.ventwig.sources]]` blocks are allowed per consuming project.
- Unknown fields in a source block are rejected with a `ConfigError` (fail loud rather than silently ignoring typos).

---

## Lock File Format

Written by ventwig after every successful sync. Tracked in the consuming project's git. Not hand-edited.

```toml
# .ventwig.lock — alongside pyproject.toml

[datahenge_appkit]
synced_commit = "f6656af3c2b4a1d9e0f8c7b2a5d4e1f0a3b6c9d2"
synced_tree   = "a18e243b41580dcc2db17badda6134f07ab2f7fc"
synced_at     = "2026-07-04T18:22:03Z"
upstream_path = "src/datahenge_appkit"
```

`upstream_path` is stored in the lock file so drift detection remains coherent even if the config value is later changed (the mismatch becomes detectable rather than silent).

Lock file writes are atomic: write to `.ventwig.lock.tmp`, then `os.replace()` — avoids partial writes on error or interrupt.

---

## Git Operations

All git interaction via `subprocess` — no `gitpython` or `pygit2`. Keeps ventwig's own dependency footprint minimal, which is the whole point.

### Shallow clone

```
git clone --depth 1 --branch <ref> <upstream> <tmpdir>
```

`--branch` works with both branch names and tags. Full commit SHA refs are not supported: shallow clone cannot target an arbitrary SHA without server cooperation, and the complexity isn't worth it. The lock file stores the resolved commit hash (`git rev-parse HEAD` after clone), giving traceability even with a moving branch ref.

### Tree hash computation (drift detection)

To compute a reproducible, content-addressed hash of a local directory without touching the consuming project's real git index:

```bash
# 1. Create a temporary index file
tmp_index=$(mktemp)

# 2. Stage the target directory into the scratch index only
GIT_INDEX_FILE="$tmp_index" git -C <repo_root> add -- <local_path>

# 3. Write the tree and capture the hash of just that subtree
GIT_INDEX_FILE="$tmp_index" git -C <repo_root> write-tree --prefix=<local_path>/

rm "$tmp_index"
```

`write-tree --prefix=<path>/` returns the hash of the subtree rooted at `<path>`, not the full index tree. This is what gets stored in and compared against `synced_tree` in the lock file. Git's own content-addressed object store makes this deterministic.

---

## Sync Algorithm

See `ventwig-project-plan.md §5` for the authoritative step-by-step. Key implementation notes:

1. **Locate `pyproject.toml`** by walking upward from `cwd` until found — same heuristic as pip and poetry. The consuming project's git root is verified before any destructive action.
2. **Temp clone dir** via `tempfile.TemporaryDirectory()` — cleaned up automatically on normal exit and on error (context manager).
3. **`upstream_path` handling**: after cloning, copy only `<tmpdir>/<upstream_path>/` into `local_path`. The rest of the clone is discarded.
4. **Destructive replace**: `shutil.rmtree(local_path)` followed by `shutil.copytree(source, local_path)`, excluding `.git/` explicitly.
5. **`git status --porcelain` check** (safety check §3 in the project plan): runs against the consuming project's repo, filtered to `local_path`, as a second independent drift signal.

---

## Error Hierarchy

```
VentwigError                 # base; all ventwig errors are catchable as this type
├── ConfigError              # malformed or missing pyproject.toml config
├── LockError                # lock file unreadable or corrupt
├── GitError                 # subprocess git call returned non-zero
├── DriftError               # local content hash doesn't match last sync
└── PreconditionError        # not inside a git working tree, or other precondition failure
```

All errors produce a single, actionable human-readable message. `cli.py` catches `VentwigError` at the top level, prints the message via `typer.echo`, and exits with code 1. Raw tracebacks are only shown when `--debug` is passed (a future flag; not in M1).

---

## CLI Surface

Target for M1–M4:

```
ventwig sync [SOURCE_NAME]
  --force     Skip drift and porcelain checks; overwrite unconditionally
  --dry-run   Show what would change; write nothing (no lock file update)
```

`ventwig status` (show drift without syncing) is deferred to M4 per the project plan.

`ventwig sync` with no `SOURCE_NAME` processes all sources in `[[tool.ventwig.sources]]` order. With a name, it processes only that source — useful for large projects with many vendored sources.

---

## Testing

### Unit tests

| File | What it covers |
|---|---|
| `test_config.py` | Parse valid and invalid `pyproject.toml` fragments; `upstream_path` defaulting; rejection of unknown fields |
| `test_lock.py` | Round-trip read/write; missing lock file (first sync); corrupt lock file |
| `test_git_ops.py` | Tree hash computation against known directory contents; `git status --porcelain` output parsing; `GitError` on non-zero exit |

### Integration tests

Fake upstream repos are created **programmatically** at test time using `subprocess` git calls inside pytest `tmp_path` fixtures. No static fixture repos committed to the ventwig repo. This avoids stale fixture state and keeps the test suite fully self-contained.

Typical integration test lifecycle:
1. `git init` a fake upstream repo in `tmp_path/upstream`
2. Commit known files (optionally under `src/` to exercise `upstream_path`)
3. `git init` a fake consuming project in `tmp_path/consumer`
4. Write a `pyproject.toml` with a `[[tool.ventwig.sources]]` entry pointing at the fake upstream (local file path, no network)
5. Call `sync.run_sync()` directly (bypasses CLI layer for unit-test speed), or invoke via `typer.testing.CliRunner` for CLI-layer coverage
6. Assert: file contents, lock file values, exit code, and that drift detection fires correctly on re-run after hand-edits

---

## Ruff Configuration

Enabled rule sets (beyond ruff defaults):

| Code | Ruleset | Purpose |
|---|---|---|
| `E`, `W` | pycodestyle | Style baseline |
| `F` | pyflakes | Undefined names, unused imports |
| `I` | isort | Import ordering |
| `UP` | pyupgrade | Enforce 3.11+ idioms |
| `B` | flake8-bugbear | Common correctness pitfalls |
| `SIM` | flake8-simplify | Redundant constructs |
| `TCH` | flake8-type-checking | Guard type-only imports under `TYPE_CHECKING` |
