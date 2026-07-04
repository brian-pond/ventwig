from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@ventwig.test"],
        check=True, capture_output=True, cwd=path,
    )
    subprocess.run(
        ["git", "config", "user.name", "Ventwig Test"],
        check=True, capture_output=True, cwd=path,
    )


def _git_commit_all(path: Path, message: str = "commit") -> None:
    subprocess.run(["git", "add", "-A"], check=True, capture_output=True, cwd=path)
    subprocess.run(["git", "commit", "-m", message], check=True, capture_output=True, cwd=path)


@pytest.fixture
def git_repo_factory(tmp_path: Path):
    """Returns a factory that creates real git repos inside tmp_path."""

    def factory(subdir: str, files: dict[str, str], branch: str = "main") -> Path:
        path = tmp_path / subdir
        path.mkdir(parents=True)
        _git_init(path)
        for fname, content in files.items():
            fpath = path / fname
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content)
        _git_commit_all(path, "initial")
        return path

    return factory


@pytest.fixture
def git_consumer_factory(tmp_path: Path):
    """Returns a factory that creates a git-initialized consumer project inside tmp_path.

    The returned directory has pyproject.toml committed so ventwig can locate it
    and find_git_root succeeds.
    """

    def factory(sources_toml: str) -> Path:
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _git_init(consumer)
        (consumer / "pyproject.toml").write_text(sources_toml)
        _git_commit_all(consumer, "init")
        return consumer

    return factory
