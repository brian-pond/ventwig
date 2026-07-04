from __future__ import annotations

from typer.testing import CliRunner

from ventwig.cli import app

runner = CliRunner()


def test_top_level_help_lists_both_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "sync" in result.output
    assert "status" in result.output


def test_sync_help_shows_options() -> None:
    result = runner.invoke(app, ["sync", "--help"])
    assert result.exit_code == 0
    assert "--force" in result.output
    assert "--dry-run" in result.output


def test_status_help() -> None:
    result = runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0
    assert "source_name" in result.output.lower() or "SOURCE_NAME" in result.output


def test_sync_config_error_exits_1(tmp_path) -> None:
    """sync invoked outside a project with no pyproject.toml exits 1 with an error message."""
    result = runner.invoke(app, ["sync"], catch_exceptions=False)
    assert result.exit_code == 1
    assert "Error:" in result.output


def test_status_config_error_exits_1(tmp_path) -> None:
    result = runner.invoke(app, ["status"], catch_exceptions=False)
    assert result.exit_code == 1
    assert "Error:" in result.output
