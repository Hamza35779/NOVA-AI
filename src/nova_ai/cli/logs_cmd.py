"""``nova logs`` — show NOVA AI log files without hunting for them.

The background daemon (``nova start``) writes ``~/.nova_ai/server.log`` and
verbose CLI runs write ``~/.nova_ai/cli.log``. Before this command users had
to know those paths; ``nova logs`` (and ``nova logs -f``) surfaces them.
"""

from __future__ import annotations

import time
from pathlib import Path

import click
from rich.console import Console

from nova_ai.core.paths import get_config_dir

console = Console()

#: Files shown when no NAME argument is given, in display order.
LOG_CANDIDATES = ("server.log", "cli.log")


def _tail(path: Path, lines: int) -> list[str]:
    """Return the last *lines* lines of *path* ([] when unreadable)."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return list(f)[-lines:]
    except OSError:
        return []


@click.command("logs")
@click.option(
    "-n", "--lines", default=50, show_default=True, help="Lines to show per file."
)
@click.option(
    "-f", "--follow", is_flag=True, help="Keep polling for new lines (Ctrl+C to stop)."
)
@click.argument("name", required=False, type=click.Choice(LOG_CANDIDATES))
def logs(lines: int, follow: bool, name: str | None) -> None:
    """Show NOVA AI log files (server daemon + CLI)."""
    paths = [get_config_dir() / name] if name else [get_config_dir() / n for n in LOG_CANDIDATES]
    existing = [p for p in paths if p.exists()]
    if not existing:
        console.print(
            "[yellow]No log files yet.[/yellow] NOVA AI writes logs to:\n"
            + "\n".join(f"  - {p}" for p in paths)
            + "\n\n  - Background daemon: logs appear after [cyan]nova start[/cyan].\n"
            "  - CLI: run with [cyan]--verbose[/cyan] to capture a cli.log."
        )
        return

    for p in existing:
        console.rule(str(p))
        for line in _tail(p, lines):
            click.echo(line.rstrip())

    if follow:
        offsets = {p: p.stat().st_size for p in existing}
        console.print("[dim]Following new lines… Ctrl+C to stop.[/dim]")
        try:
            while True:
                for p in existing:
                    try:
                        size = p.stat().st_size
                    except OSError:
                        continue
                    last = offsets.get(p, 0)
                    if size < last:  # rotated/truncated — start over
                        last = 0
                    if size > last:
                        try:
                            with p.open("r", encoding="utf-8", errors="replace") as f:
                                f.seek(last)
                                click.echo(f.read().rstrip())
                            offsets[p] = size
                        except OSError:
                            continue
                time.sleep(1.0)
        except KeyboardInterrupt:
            console.print("\n[dim]Stopped.[/dim]")


if __name__ == "__main__":  # pragma: no cover
    logs()
