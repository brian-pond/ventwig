from __future__ import annotations

from pathlib import Path

import pytest

from ventwig.errors import GitError, PreconditionError
from ventwig.git_ops import clone, compute_tree_hash, find_git_root, has_uncommitted_changes


def test_clone_returns_full_sha(tmp_path: Path, git_repo_factory) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    dest = tmp_path / "dest"
    commit = clone(str(upstream), "main", dest)
    assert len(commit) == 40
    assert dest.is_dir()
    assert (dest / "foo.py").read_text() == "x = 1"


def test_clone_copies_nested_files(tmp_path: Path, git_repo_factory) -> None:
    upstream = git_repo_factory("upstream", {
        "src/lib/a.py": "a = 1",
        "src/lib/b.py": "b = 2",
    })
    dest = tmp_path / "dest"
    clone(str(upstream), "main", dest)
    assert (dest / "src" / "lib" / "a.py").read_text() == "a = 1"


def test_clone_raises_on_missing_repo(tmp_path: Path) -> None:
    with pytest.raises(GitError):
        clone(str(tmp_path / "nonexistent"), "main", tmp_path / "dest")


def test_clone_raises_on_bad_ref(tmp_path: Path, git_repo_factory) -> None:
    upstream = git_repo_factory("upstream", {"foo.py": "x = 1"})
    with pytest.raises(GitError):
        clone(str(upstream), "no-such-branch", tmp_path / "dest")


# --- compute_tree_hash ---


def test_tree_hash_is_40_chars(tmp_path: Path) -> None:
    d = tmp_path / "mydir"
    d.mkdir()
    (d / "a.py").write_text("x = 1")
    assert len(compute_tree_hash(d)) == 40


def test_tree_hash_is_deterministic(tmp_path: Path) -> None:
    d = tmp_path / "mydir"
    d.mkdir()
    (d / "a.py").write_text("x = 1")
    assert compute_tree_hash(d) == compute_tree_hash(d)


def test_tree_hash_differs_on_content_change(tmp_path: Path) -> None:
    d = tmp_path / "mydir"
    d.mkdir()
    (d / "a.py").write_text("x = 1")
    h1 = compute_tree_hash(d)
    (d / "a.py").write_text("x = 2")
    h2 = compute_tree_hash(d)
    assert h1 != h2


def test_tree_hash_differs_on_new_file(tmp_path: Path) -> None:
    d = tmp_path / "mydir"
    d.mkdir()
    (d / "a.py").write_text("x = 1")
    h1 = compute_tree_hash(d)
    (d / "b.py").write_text("y = 2")
    h2 = compute_tree_hash(d)
    assert h1 != h2


def test_tree_hash_same_for_identical_contents_in_different_paths(tmp_path: Path) -> None:
    d1 = tmp_path / "dir1"
    d1.mkdir()
    (d1 / "a.py").write_text("x = 1")

    d2 = tmp_path / "dir2"
    d2.mkdir()
    (d2 / "a.py").write_text("x = 1")

    assert compute_tree_hash(d1) == compute_tree_hash(d2)


def test_tree_hash_handles_nested_directories(tmp_path: Path) -> None:
    d = tmp_path / "mydir"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "a.py").write_text("x = 1")
    (d / "top.py").write_text("y = 2")
    h = compute_tree_hash(d)
    assert len(h) == 40


# --- find_git_root ---


def test_find_git_root_returns_root(tmp_path: Path, git_repo_factory) -> None:
    repo = git_repo_factory("myrepo", {"foo.py": "x = 1"})
    assert find_git_root(repo) == repo


def test_find_git_root_from_subdir(tmp_path: Path, git_repo_factory) -> None:
    repo = git_repo_factory("myrepo", {"sub/foo.py": "x = 1"})
    assert find_git_root(repo / "sub") == repo


def test_find_git_root_raises_outside_repo(tmp_path: Path) -> None:
    plain_dir = tmp_path / "notarepo"
    plain_dir.mkdir()
    with pytest.raises(PreconditionError, match="git working tree"):
        find_git_root(plain_dir)


# --- has_uncommitted_changes ---


def test_has_uncommitted_changes_false_when_clean(tmp_path: Path, git_repo_factory) -> None:
    repo = git_repo_factory("repo", {"vendor/lib/foo.py": "x = 1"})
    assert not has_uncommitted_changes(repo, repo / "vendor" / "lib")


def test_has_uncommitted_changes_true_when_tracked_file_modified(
    tmp_path: Path, git_repo_factory
) -> None:
    repo = git_repo_factory("repo", {"vendor/lib/foo.py": "x = 1"})
    (repo / "vendor" / "lib" / "foo.py").write_text("x = MODIFIED")
    assert has_uncommitted_changes(repo, repo / "vendor" / "lib")


def test_has_uncommitted_changes_false_for_untracked(tmp_path: Path, git_repo_factory) -> None:
    repo = git_repo_factory("repo", {"existing.py": "x = 1"})
    new_dir = repo / "vendor" / "lib"
    new_dir.mkdir(parents=True)
    (new_dir / "new.py").write_text("new = True")
    assert not has_uncommitted_changes(repo, new_dir)


def test_has_uncommitted_changes_false_outside_repo(tmp_path: Path, git_repo_factory) -> None:
    repo = git_repo_factory("repo", {"foo.py": "x = 1"})
    outside = tmp_path / "outside"
    outside.mkdir()
    assert not has_uncommitted_changes(repo, outside)
