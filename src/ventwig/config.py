from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError

_KNOWN_SOURCE_KEYS = {"name", "local_path", "upstream", "upstream_path", "ref"}
_REQUIRED_SOURCE_KEYS = {"name", "local_path", "upstream", "ref"}


@dataclass(frozen=True)
class SourceConfig:
    name: str
    local_path: Path
    upstream: str
    ref: str
    upstream_path: str | None = None


def _find_pyproject(start: Path) -> Path:
    for directory in [start, *start.parents]:
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    raise ConfigError("No pyproject.toml found in current directory or any parent.")


def load_sources(start: Path | None = None) -> tuple[Path, list[SourceConfig]]:
    """Locate pyproject.toml from start (default: cwd) and parse ventwig sources."""
    if start is None:
        start = Path.cwd()

    pyproject_path = _find_pyproject(start)

    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)

    raw_sources = data.get("tool", {}).get("ventwig", {}).get("sources", [])
    if not raw_sources:
        raise ConfigError("No [[tool.ventwig.sources]] entries found in pyproject.toml.")

    sources: list[SourceConfig] = []
    for i, raw in enumerate(raw_sources):
        label = f"[[tool.ventwig.sources]] entry #{i + 1}"
        unknown = set(raw.keys()) - _KNOWN_SOURCE_KEYS
        if unknown:
            raise ConfigError(f"Unknown field(s) in {label}: {', '.join(sorted(unknown))}")

        missing = _REQUIRED_SOURCE_KEYS - set(raw.keys())
        if missing:
            field = next(iter(sorted(missing)))
            raise ConfigError(f"{label} is missing required field '{field}'.")

        sources.append(
            SourceConfig(
                name=raw["name"],
                local_path=pyproject_path.parent / raw["local_path"],
                upstream=raw["upstream"],
                ref=raw["ref"],
                upstream_path=raw.get("upstream_path"),
            )
        )

    return pyproject_path, sources
