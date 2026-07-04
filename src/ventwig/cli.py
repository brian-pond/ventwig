from __future__ import annotations

import typer

from .errors import VentwigError
from .sync import run_status, run_sync

app = typer.Typer(help="Vendor git source directories into your project tree.")


@app.command()
def sync(
    source_name: str | None = typer.Argument(
        None, help="Name of a specific source to sync. Syncs all sources if omitted."
    ),
    force: bool = typer.Option(False, "--force", help="Skip drift and porcelain checks."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change; write nothing."),
) -> None:
    """Sync vendored sources from upstream git repositories."""
    try:
        run_sync(source_name=source_name, dry_run=dry_run, force=force)
    except VentwigError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None


@app.command()
def status(
    source_name: str | None = typer.Argument(
        None, help="Name of a specific source to check. Checks all sources if omitted."
    ),
) -> None:
    """Show sync status for vendored sources without modifying anything.

    Exits 0 only when every source is clean (synced and unmodified).
    Exits 1 if any source is drifted, has staged changes, is untracked, or has never been synced.
    """
    try:
        all_clean = run_status(source_name=source_name)
    except VentwigError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None
    if not all_clean:
        raise typer.Exit(1)
