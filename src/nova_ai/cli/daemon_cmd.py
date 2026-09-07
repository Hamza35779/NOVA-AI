"""``nova start|stop|restart|status`` — daemon management commands."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time

import click
from rich.console import Console

from nova_ai.core.config import DEFAULT_CONFIG_DIR, load_config
from nova_ai.core.utils import soft_fail

logger = logging.getLogger(__name__)

_PID_FILE = DEFAULT_CONFIG_DIR / "server.pid"
_LOG_FILE = DEFAULT_CONFIG_DIR / "server.log"


def _read_pid() -> int | None:
    """Read PID from pid file, return None if not found or stale."""
    if not _PID_FILE.exists():
        return None
    try:
        pid = int(_PID_FILE.read_text().strip())
        # Check if process is still running
        os.kill(pid, 0)
        return pid
    except (ValueError, OSError):
        _PID_FILE.unlink(missing_ok=True)
        return None


def _write_pid(pid: int) -> None:
    """Write PID to pid file."""
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(pid))


@click.group()
def daemon() -> None:
    """Manage the NOVA AI server daemon."""


@daemon.command()
@click.option("--host", default=None, help="Bind address.")
@click.option("--port", default=None, type=int, help="Port number.")
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option("-m", "--model", "model_name", default=None, help="Default model.")
@click.option("-a", "--agent", "agent_name", default=None, help="Agent type.")
def start(
    host: str | None,
    port: int | None,
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
) -> None:
    """Start the NOVA AI server as a background daemon."""
    console = Console(stderr=True)

    existing = _read_pid()
    if existing is not None:
        console.print(f"[yellow]Server already running (PID {existing}).[/yellow]")
        console.print("Use 'nova stop' to stop it first, or 'nova restart'.")
        sys.exit(1)

    config = load_config()
    bind_host = host or config.server.host
    bind_port = port or config.server.port

    # Build command to run nova serve
    cmd = [sys.executable, "-m", "nova_ai.cli", "serve"]
    if host:
        cmd.extend(["--host", host])
    if port:
        cmd.extend(["--port", str(port)])
    if engine_key:
        cmd.extend(["--engine", engine_key])
    if model_name:
        cmd.extend(["--model", model_name])
    if agent_name:
        cmd.extend(["--agent", agent_name])

    # Start as background process
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    log_fh = open(_LOG_FILE, "a")  # noqa: SIM115
    proc = subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=log_fh,
        start_new_session=True,
    )
    _write_pid(proc.pid)

    console.print(
        f"[green]NOVA AI server started[/green] (PID {proc.pid})\n"
        f"  URL: http://{bind_host}:{bind_port}\n"
        f"  Log: {_LOG_FILE}"
    )


@daemon.command()
def stop() -> None:
    """Stop the running NOVA AI server daemon."""
    console = Console(stderr=True)
    pid = _read_pid()
    if pid is None:
        console.print("[yellow]No running server found.[/yellow]")
        sys.exit(1)

    # The old version swallowed both the kill failure and the SIGKILL
    # fallback (`except OSError: pass`), then unlinked the PID file and
    # printed "Server stopped" unconditionally — a failed terminate left
    # the server live with no pidfile and exit code 0. Gate everything on
    # confirmed death so callers see the real outcome.
    stopped = False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        console.print(f"[red]Failed to signal PID {pid}: {exc}[/red]")
        sys.exit(1)

    # Wait up to 10 seconds for graceful shutdown
    for _ in range(20):
        time.sleep(0.5)
        try:
            os.kill(pid, 0)
        except OSError:
            stopped = True
            break

    if not stopped:
        # Force kill if still running. SIGKILL doesn't exist on Windows —
        # fall back to SIGTERM (already sent) or the strongest available
        # signal so the failure path below can actually be reached.
        force = getattr(signal, "SIGKILL", signal.SIGTERM)
        try:
            os.kill(pid, force)
        except OSError:
            pass
        # Give the force-kill a moment to take effect
        for _ in range(6):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except OSError:
                stopped = True
                break

    if not stopped:
        console.print(
            f"[red]Failed to stop server (PID {pid} still alive). "
            "PID file left in place.[/red]"
        )
        sys.exit(1)

    _PID_FILE.unlink(missing_ok=True)
    console.print(f"[green]Server stopped[/green] (PID {pid}).")


@daemon.command()
@click.pass_context
def restart(ctx: click.Context) -> None:
    """Restart the NOVA AI server daemon."""
    console = Console(stderr=True)
    pid = _read_pid()
    if pid is not None:
        console.print(f"Stopping server (PID {pid})...")
        ctx.invoke(stop)
    ctx.invoke(start)


@daemon.command()
def status() -> None:
    """Show status of the NOVA AI server daemon."""
    console = Console(stderr=True)
    pid = _read_pid()
    if pid is None:
        console.print("[yellow]Server is not running.[/yellow]")
        return

    # Get process info
    uptime_info = ""
    try:
        import psutil

        proc = psutil.Process(pid)
        uptime = time.time() - proc.create_time()
        hours, remainder = divmod(int(uptime), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_info = f"\n  Uptime: {hours}h {minutes}m {seconds}s"
    except (ImportError, Exception) as exc:
        soft_fail(logger, exc, "optional CLI step")

    config = load_config()
    console.print(
        f"[green]Server is running[/green] (PID {pid}){uptime_info}\n"
        f"  URL: http://{config.server.host}:{config.server.port}\n"
        f"  Log: {_LOG_FILE}"
    )


__all__ = ["daemon", "start", "stop", "restart", "status"]
