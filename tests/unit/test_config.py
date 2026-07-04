from __future__ import annotations

from pathlib import Path

import pytest

from ventwig.config import load_sources
from ventwig.errors import ConfigError


def _write_pyproject(path: Path, content: str) -> None:
    (path / "pyproject.toml").write_text(content)


def test_load_basic_source(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, """
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "https://example.com/mylib.git"
ref = "main"
""")
    _, sources = load_sources(tmp_path)
    assert len(sources) == 1
    s = sources[0]
    assert s.name == "mylib"
    assert s.upstream == "https://example.com/mylib.git"
    assert s.ref == "main"
    assert s.upstream_path is None
    assert s.local_path == tmp_path / "vendor" / "mylib"


def test_load_source_with_upstream_path(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, """
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "https://example.com/mylib.git"
upstream_path = "src/mylib"
ref = "main"
""")
    _, sources = load_sources(tmp_path)
    assert sources[0].upstream_path == "src/mylib"


def test_load_multiple_sources(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, """
[[tool.ventwig.sources]]
name = "lib_a"
local_path = "vendor/lib_a"
upstream = "https://example.com/a.git"
ref = "main"

[[tool.ventwig.sources]]
name = "lib_b"
local_path = "vendor/lib_b"
upstream = "https://example.com/b.git"
ref = "v1.0"
""")
    _, sources = load_sources(tmp_path)
    assert len(sources) == 2
    assert sources[0].name == "lib_a"
    assert sources[1].name == "lib_b"
    assert sources[1].ref == "v1.0"


def test_find_pyproject_walks_up(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, """
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "https://example.com/mylib.git"
ref = "main"
""")
    subdir = tmp_path / "a" / "b" / "c"
    subdir.mkdir(parents=True)
    _, sources = load_sources(subdir)
    assert len(sources) == 1


def test_pyproject_path_returned(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, """
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "https://example.com/mylib.git"
ref = "main"
""")
    pyproject_path, _ = load_sources(tmp_path)
    assert pyproject_path == tmp_path / "pyproject.toml"


def test_unknown_field_raises(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, """
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "https://example.com/mylib.git"
ref = "main"
typo_field = "oops"
""")
    with pytest.raises(ConfigError, match="Unknown field"):
        load_sources(tmp_path)


def test_missing_required_field_raises(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, """
[[tool.ventwig.sources]]
name = "mylib"
local_path = "vendor/mylib"
upstream = "https://example.com/mylib.git"
""")
    with pytest.raises(ConfigError, match="missing required field 'ref'"):
        load_sources(tmp_path)


def test_no_pyproject_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="No pyproject.toml found"):
        load_sources(tmp_path)


def test_no_sources_raises(tmp_path: Path) -> None:
    _write_pyproject(tmp_path, "[project]\nname = 'foo'\n")
    with pytest.raises(ConfigError, match=r"No \[\[tool\.ventwig\.sources\]\]"):
        load_sources(tmp_path)
