# ventwig — Project Plan

**Status:** Design complete, implementation not started
**License (planned):** MIT
**Hosting (planned):** Public GitHub, personal account (not Datahenge LLC — see Decisions Log)

---

## 1. Problem Statement

Building Python CLI tools and daemons repeatedly requires the same boilerplate:

- Environment-variable loading with correct precedence (explicit args > real env vars > project `.env` > XDG-located fallback `.env` > field defaults)
- Declaring which config values are mandatory vs. optional, with real type/range/enum validation
- Structured or plain-text logging to stdout, with level and format controlled by config

That boilerplate has already been solved once, as `datahenge-appkit` (`config.py`, `logging_setup.py`, `bootstrap.py`). The problem is *reuse* across a growing number of small, independent CLI/daemon projects — without:

- Adding a runtime PyPI dependency that a stranger forking one of these apps would have to explain or justify
- Losing a canonical, single source of truth for the boilerplate (drifting copies across projects)
- Relying on any manual copy/paste discipline

**ventwig** is the tool that closes that gap: a small CLI, config-driven via `pyproject.toml`, that pulls a canonical copy of source files from a public git repo directly into a project's own tree — vendored, not installed.

---

## 2. Core Design Decisions

| Decision | Rationale |
|---|---|
| Vendor via **clone + destructive replace**, not `git subtree` | `git subtree`'s history-preserving merge buys little once syncs are squashed anyway; a plain replace is simpler, more transparent, and matches the "this directory is generated, don't hand-edit it" intent |
| Drift detection via **git tree hashes**, not a custom hashing scheme | Git already computes a deterministic, content-addressed hash for any directory at every commit (`git write-tree` against a scratch index gives the same hash for a plain, untracked directory) — no need to invent or maintain a parallel algorithm |
| Compare local content against the **last-synced hash only**, not full upstream history | The question that matters is "has this drifted since I last placed it here," not "was this content ever public" — a single stored value answers that in O(1) |
| Config lives in **`pyproject.toml`**, under `[[tool.ventwig.sources]]` | Same convention as `pip`'s own `vendoring` tool and `vendy` — discoverable, versioned with the project, no separate config format to maintain |
| ventwig itself is a **dev-time tool**, never a runtime dependency of the projects it vendors into | This is the design choice that actually resolves "why is there an odd dependency" — there isn't one; ventwig never appears in `[project.dependencies]` of any consuming app |
| Refuse to run destructively unless the target directory is inside a **git-controlled project** | Makes the drift check meaningful and gives the user an undo path (`git checkout`, `git stash`) if something unexpected gets overwritten |

---

## 3. Configuration Format

```toml
# pyproject.toml, in each consuming project

[[tool.ventwig.sources]]
name = "datahenge_appkit"
local_path = "vendor/datahenge_appkit"
upstream = "https://github.com/<you>/datahenge-appkit.git"
ref = "main"
```

Multiple `[[tool.ventwig.sources]]` blocks are allowed per project — one per vendored dependency.

## 4. Lock File

Written by ventwig after every successful sync, read before the next one. Not hand-edited.

```toml
# .ventwig.lock, alongside pyproject.toml — tracked in git

[datahenge_appkit]
synced_commit = "f6656af..."
synced_tree   = "a18e243b41580dcc2db17badda6134f07ab2f7fc"
synced_at     = "2026-07-04T18:22:03Z"
```

---

## 5. Sync Algorithm

```
for each [[tool.ventwig.sources]] entry:
    1. Confirm the consuming project is inside a git working tree.
       Abort with a clear error if not.

    2. If local_path exists:
         a. Compute its tree hash (scratch GIT_INDEX_FILE + `git add -A` + `git write-tree`)
         b. Compare against .ventwig.lock's synced_tree for this source
         c. If mismatch and --force not passed: abort, warn the user
            their local copy doesn't match what was last synced
            (i.e. it looks hand-edited)

    3. `git clone <upstream> <ref>` into a temp directory

    4. Destructively replace local_path's contents with the clone's
       (minus its .git directory)

    5. Recompute the tree hash of the new local_path content

    6. Write .ventwig.lock: synced_commit, synced_tree, synced_at

    7. Report a one-line summary of what changed (git diff --stat
       against the previous commit is sufficient, since local_path
       is a normal tracked directory in the consuming project)
```

---

## 6. Safety Checks (defense in depth)

1. **Git-controlled precondition** — refuse to operate outside a git working tree.
2. **Tree-hash drift check** — refuses to overwrite content that doesn't match the last known sync (see §5, step 2).
3. **`git status --porcelain` check on the target path** — an independent, cheap second check: if the consuming project's own git index shows uncommitted changes under `local_path`, ventwig warns even if the tree hash happens to match a previous sync (e.g., a revert-then-edit scenario).
4. **`--force` flag** — explicit override for both checks, for the rare case the user genuinely wants to discard local changes.

---

## 7. Explicit Non-Goals

- **Not** attempting PyPI-package vendoring (that's what `vendoring`/`vendy` already do — different problem)
- **Not** using `git submodule` or `git subtree` — see Decisions Log
- **Not** supporting bidirectional sync (pushing local fixes back upstream) — canonical source is one-way, edits always happen in the upstream repo
- **Not** designed for marketing or adoption — this is infrastructure for one person's growing set of small tools, not a product

---

## 8. Build Milestones

- [ ] **M1 — MVP clone/replace, no safety checks.** Parse `pyproject.toml`, clone + destructive replace, no drift detection. Enough to validate the config format and basic mechanics.
- [ ] **M2 — Drift detection.** Implement scratch-index tree hashing, `.ventwig.lock` read/write, abort-on-mismatch behavior.
- [ ] **M3 — Safety checks.** Git-controlled precondition, `git status --porcelain` check, `--force` flag.
- [ ] **M4 — CLI polish.** `--dry-run`, clear/actionable error messages, `ventwig sync [source_name]` to target a single source instead of all of them.
- [ ] **M5 — Packaging.** MIT license, minimal README (what it does, why it exists, in a few sentences — no marketing tone), publish to PyPI as `ventwig`.
- [ ] **M6 — First real validation.** Vendor `datahenge-appkit` (`config.py`, `logging_setup.py`, `bootstrap.py`) into a real test project using ventwig end-to-end.

---

## 9. Testing Plan (M6, immediate next step)

1. Create (or reuse) `datahenge-appkit` as a public GitHub repo containing the config/logging boilerplate already built and verified earlier:
   - `config.py` — `pydantic-settings`-based `Settings`, XDG-located `.env` fallback, mandatory/optional/typed/enum fields
   - `logging_setup.py` — `structlog`-based stdout logging, switchable JSON/text rendering, level from config
   - `bootstrap.py` — single `bootstrap_app(settings_cls, app_name)` call tying both together
2. Create a throwaway test project (a small CLI or daemon skeleton).
3. Add a `[[tool.ventwig.sources]]` entry pointing `vendor/datahenge_appkit` at the `datahenge-appkit` repo.
4. Run `ventwig sync` — confirm the vendored files land correctly and `bootstrap_app(...)` works from the vendored copy.
5. Hand-edit a vendored file, re-run `ventwig sync` — confirm it detects drift and refuses without `--force`.
6. Push a real change to `datahenge-appkit`, re-run `ventwig sync` — confirm the update lands and the lock file updates.

---

## 10. Decisions Log (naming and architecture provenance)

- Considered and rejected as names, in order: `vendortree` (too literal), `graft`/`scion`/`transplant`/`rootstock` (all taken on PyPI, several heavily crowded with near-variants), `scyon` (respelling doesn't defuse the `scion` brand collision with an existing Google agent-orchestration tool), `borrow` (wrong connotation — implies temporary loan, not permanent adoption; also collides with Rust's borrow-checker terminology), `annex` and `splice` (both crowded with real, adjacent tools — `git-annex`, `splicemachine`), `tendril`/`vendril` (tendril carries a dark, grasping connotation common in horror writing), `ventree` (reads as a member of the existing `vntree`/`deptree`/`pip-tree` naming family).
- **`ventwig`** selected: clean on PyPI at time of check, no crowded neighborhood of near-variants, no adjacent tech-product collision, and "twig" carries the right tone — small, plain, unremarkable — matching the tool's actual scope and ambition.
- Vendoring mechanism: considered `git subtree` first; dropped in favor of clone + destructive replace once it became clear that `--squash` (needed to keep consuming-project history clean) already discards most of subtree's history-preservation advantage, making the added mechanism not worth its complexity.
- Hosting: `datahenge-appkit` and `ventwig` both planned for public GitHub, deliberately not scoped under the Datahenge LLC name or account, since the business's continuation is presently undecided and the tooling shouldn't be coupled to that decision.

---

## 11. Open Questions

- Exact CLI argument surface beyond `ventwig sync` (e.g., `ventwig status` to show drift without syncing?) — defer until M4.
- Whether `.ventwig.lock` should be per-source files or one combined file — current plan is one combined TOML file; revisit if it becomes unwieldy.
