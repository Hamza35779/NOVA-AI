"""``nova dev-watch`` — build/terminal diagnostics with self-healing.

Runs a build or test command, classifies failures using the same
markers as the self-healing agent, and (optionally) asks the
``self_healing_react`` agent for a diagnosis and fix suggestion.

Examples:
    nova dev-watch -c "pytest -q"
    nova dev-watch -c "cargo build" --watch --interval 60
    nova dev-watch -c "npx tsc -b" --on-failure suggest
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nova_ai.core.utils import soft_fail

logger = logging.getLogger(__name__)

# Keep the tail of failing output — tracebacks put the exception last,
# mirroring self_healing._trim_error without importing a private helper.
_MAX_ERROR_CHARS = 4000


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DevWatchRun:
    """Outcome of one command execution under the watcher."""

    command: str
    returncode: int
    status: str  # "pass" | "fail"
    failure_type: Optional[str]  # classify_failure category
    output: str
    suggestion: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _combine_output(stdout: str, stderr: str) -> str:
    parts: List[str] = []
    if stdout and stdout.strip():
        parts.append(stdout.rstrip())
    if stderr and stderr.strip():
        parts.append("=== stderr ===\n" + stderr.rstrip())
    return "\n".join(parts)


def _trim_output(content: str, limit: int = _MAX_ERROR_CHARS) -> str:
    content = content or ""
    if len(content) <= limit:
        return content
    return "…(truncated head)…\n" + content[-limit:]


def _post_to_server(run: DevWatchRun) -> None:
    """Best-effort: report the run to the local server's devwatch API."""
    try:
        import json as _json
        import urllib.request

        from nova_ai.core.config import DEFAULT_CONFIG_DIR

        port = 8000
        try:
            import tomllib

            cfg_path = DEFAULT_CONFIG_DIR / "config.toml"
            if cfg_path.exists():
                port = int(
                    tomllib.loads(cfg_path.read_text(encoding="utf-8"))
                    .get("server", {})
                    .get("port", 8000)
                )
        except Exception:  # noqa: BLE001
            pass

        payload = _json.dumps(
            {
                "command": run.command,
                "status": run.status,
                "returncode": run.returncode,
                "failure_type": run.failure_type,
                "output": _trim_output(run.output, 2000),
                "suggestion": run.suggestion[:2000],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/devwatch/runs",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2).close()
    except Exception:  # noqa: BLE001
        logger.debug("Could not report dev-watch run to server", exc_info=True)


def _classify(returncode: int, output: str) -> Optional[str]:
    """Classify a command run via the self-healing failure markers.

    A non-zero exit is a failure; so is a zero exit whose output embeds
    a known error marker (some runners exit 0 while printing errors).
    """
    from nova_ai.agents.self_healing import classify_failure
    from nova_ai.core.types import ToolResult

    result = ToolResult(
        tool_name="dev_watch",
        content=output,
        success=returncode == 0,
    )
    return classify_failure(result)


def _consult_healer(command: str, output: str, failure_type: str, mode: str) -> str:
    """Ask the self-healing agent to diagnose/repair a failing run."""
    from nova_ai.core.config import load_config
    from nova_ai.system import SystemBuilder

    trimmed = _trim_output(output)
    instruction = (
        "Propose the minimal fix (exact edits or commands). "
        "Do not apply anything — the user will review."
        if mode == "suggest"
        else "Apply the fix using your tools, then summarize what you changed."
    )
    prompt = (
        "A monitored build/test command failed in `nova dev-watch`.\n\n"
        f"Command: {command}\n"
        f"Failure category: {failure_type}\n\n"
        "Error output (tail):\n"
        f"```\n{trimmed}\n```\n\n"
        f"{instruction}"
    )
    system = SystemBuilder(load_config()).build()
    return system.ask(prompt, agent="self_healing_react")


def _run_once(
    command: str,
    on_failure: str,
    timeout: int,
    shell: bool,
    console: Console,
) -> DevWatchRun:
    """Run the command once and handle failure consultation."""
    try:
        proc = subprocess.run(
            command,
            shell=shell,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        returncode = proc.returncode
        output = _combine_output(proc.stdout or "", proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        returncode = -1
        partial_out = ""
        if isinstance(exc.stdout, bytes):
            partial_out = exc.stdout.decode("utf-8", errors="replace")
        elif isinstance(exc.stdout, str):
            partial_out = exc.stdout
        output = _combine_output(partial_out, f"execution timed out after {timeout}s")
    except FileNotFoundError as exc:
        returncode = -1
        output = f"command not found: {command}\n{exc}"
    except OSError as exc:
        returncode = -1
        output = f"OS error running command: {exc}"

    failure_type = _classify(returncode, output)
    run = DevWatchRun(
        command=command,
        returncode=returncode,
        status="pass" if failure_type is None else "fail",
        failure_type=failure_type,
        output=output,
    )

    if run.status == "fail" and on_failure != "off":
        console.print(f"  [red]FAIL[/red] exit {returncode} ({failure_type})")
        try:
            suggestion = _consult_healer(command, output, failure_type or "unknown", on_failure)
            run.suggestion = suggestion
        except Exception as exc:  # noqa: BLE001
            soft_fail(logger, exc, "Healer consultation failed for dev-watch")
            run.suggestion = ""
    _post_to_server(run)
    return run


def _print_run(run: DevWatchRun, index: int, console: Console) -> None:
    console.print(f"\n[bold]→ {run.command}[/bold] [dim](run #{index})[/dim]")
    if run.status == "pass":
        console.print(f"  [green]PASS[/green] exit {run.returncode}")
        return
    console.print(f"  [red]FAIL[/red] exit {run.returncode} ({run.failure_type})")
    if run.suggestion:
        console.print(
            Panel(
                run.suggestion.strip(),
                title="[yellow]Self-healing suggestion[/yellow]",
                border_style="yellow",
            )
        )
    elif run.failure_type:
        console.print("[dim]  (no suggestion — failure not classified)[/dim]")


def _print_history(runs: List[DevWatchRun], console: Console) -> None:
    if not runs:
        return
    table = Table(title="dev-watch history")
    table.add_column("#", justify="right")
    table.add_column("Command", overflow="fold")
    table.add_column("Status")
    table.add_column("Exit", justify="right")
    table.add_column("Category")
    table.add_column("Suggested", justify="center")
    for i, run in enumerate(runs, 1):
        table.add_row(
            str(i),
            run.command,
            f"[green]{run.status.upper()}[/green]"
            if run.status == "pass"
            else f"[red]{run.status.upper()}[/red]",
            str(run.returncode),
            run.failure_type or "-",
            "yes" if run.suggestion else "-",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("dev-watch", help="Watch a build/test command and self-diagnose failures.")
@click.option(
    "--command",
    "-c",
    required=True,
    help='Build/test command to run (e.g. "pytest -q", "cargo build").',
)
@click.option(
    "--watch",
    is_flag=True,
    default=False,
    help="Keep re-running the command on an interval (Ctrl+C to stop).",
)
@click.option(
    "--interval",
    type=int,
    default=30,
    show_default=True,
    help="Seconds between runs in --watch mode.",
)
@click.option(
    "--timeout",
    type=int,
    default=600,
    show_default=True,
    help="Seconds before a single run is killed as timed out.",
)
@click.option(
    "--on-failure",
    type=click.Choice(["suggest", "fix", "off"]),
    default="suggest",
    show_default=True,
    help="What to do when the command fails.",
)
@click.option(
    "--shell/--no-shell",
    default=True,
    show_default=True,
    help="Run the command through the system shell.",
)
def dev_watch(
    command: str,
    watch: bool,
    interval: int,
    timeout: int,
    on_failure: str,
    shell: bool,
) -> None:
    """Run a build/test command and surface self-healing fix suggestions."""
    console = Console()
    interval = max(1, interval)
    runs: List[DevWatchRun] = []
    last_signature: Optional[str] = None

    while True:
        index = len(runs) + 1
        run = _run_once(command, on_failure, timeout, shell, console)
        runs.append(run)
        _print_run(run, index, console)

        signature = hashlib.sha256(
            f"{run.returncode}:{run.output}".encode("utf-8", errors="replace")
        ).hexdigest()
        unchanged = signature == last_signature
        last_signature = signature

        if not watch:
            break

        if run.status == "fail" and unchanged:
            console.print("[dim]Output unchanged — skipping re-consultation.[/dim]")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            break

    _print_history(runs, console)
    failed = sum(1 for r in runs if r.status == "fail")
    if failed:
        console.print(f"[red]{failed}/{len(runs)} run(s) failed.[/red]")
