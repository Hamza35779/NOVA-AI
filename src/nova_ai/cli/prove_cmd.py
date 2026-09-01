"""``nova prove`` — the Model Proving Ground: A/B models on YOUR traces.

Every trigger shares one pipeline (``learning.proving.pipeline.run_proving``):
synthesize a benchmark from high-feedback traces, run candidate and
incumbent head-to-head under the same judge, and report a per-query-class
verdict. The gauntlet itself is read-only — only ``nova prove adopt`` (or
``[learning.proving] auto_adopt``) changes routing behavior.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from nova_ai.core.config import load_config

console = Console()


def _proving_root() -> Path:
    from nova_ai.core.paths import get_config_dir

    return get_config_dir() / "learning" / "proving"


def _run_store():
    from nova_ai.learning.proving.store import ProvingRunStore

    return ProvingRunStore(_proving_root() / "runs.db")


def _effective_proving_config():
    learning_cfg = load_config().learning
    return learning_cfg, learning_cfg.proving


@click.group()
def prove() -> None:
    """Prove whether a new model actually beats the incumbent on your traces."""


@prove.command()
@click.argument("candidate")
@click.option("--incumbent", default=None, help="Opponent (default: your default model).")
@click.option(
    "--foreground",
    is_flag=True,
    default=False,
    help="Run in the foreground and print the scorecard (default: background).",
)
@click.option(
    "--adopt",
    is_flag=True,
    default=False,
    help="Adopt winners immediately (otherwise wait for `nova prove adopt`).",
)
def run(candidate: str, incumbent: str | None, foreground: bool, adopt: bool) -> None:
    """Run the gauntlet: CANDIDATE vs the incumbent on your traces."""
    learning_cfg, cfg = _effective_proving_config()
    if not cfg.enabled:
        console.print(
            "[yellow]The proving ground is disabled.[/yellow] Enable it with:\n\n"
            "  [learning.proving]\n"
            '  enabled = true\n\n'
            "in ~/.nova_ai/config.toml"
        )
        raise SystemExit(1)

    store = _run_store()
    if store.is_running():
        console.print("[yellow]A proving run is already in flight.[/yellow]")
        console.print("Check progress: [bold]nova prove status[/bold]")
        raise SystemExit(1)

    if foreground:
        record = _run_foreground(cfg, candidate, incumbent, adopt)
        _print_run(record)
        raise SystemExit(0 if record.get("status") == "completed" else 1)

    _spawn_background(candidate, incumbent, adopt)
    console.print("[green]Proving run started in the background.[/green]")
    console.print("Check progress: [bold]nova prove status[/bold]")


def _run_foreground(cfg, candidate: str, incumbent: str | None, adopt: bool):
    from nova_ai.core.paths import get_config_dir
    from nova_ai.learning.proving.pipeline import run_proving
    from nova_ai.traces.store import TraceStore

    return run_proving(
        candidate=candidate,
        trace_store=TraceStore(get_config_dir() / "traces.db"),
        config=cfg,
        run_store=_run_store(),
        incumbent=incumbent,
        proving_root=_proving_root(),
        trigger="manual",
        adopt=True if adopt else None,
    )


def _spawn_background(candidate: str, incumbent: str | None, adopt: bool) -> None:
    """Launch a detached child process running the pipeline.

    Windows-safe (same pattern as ``train_cmd._spawn_background``):
    DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, output to a log file.
    """
    from nova_ai.core.config import DEFAULT_CONFIG_DIR

    log_path = _proving_root() / "last_run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    python = sys.executable
    script = (
        "from nova_ai.cli.prove_cmd import _run_background_entry;"
        f"_run_background_entry({candidate!r}, {incumbent!r}, {adopt!r})"
    )
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        close_fds = False
    else:
        close_fds = True

    with open(log_path, "ab") as log_f:
        subprocess.Popen(
            [python, "-c", script],
            stdout=log_f,
            stderr=log_f,
            stdin=subprocess.DEVNULL,
            close_fds=close_fds,
            creationflags=creationflags,
            start_new_session=sys.platform != "win32",
            env={**os.environ, "NOVA_PROVING_BACKGROUND": "1"},
            cwd=str(DEFAULT_CONFIG_DIR),
        )


def _run_background_entry(candidate: str, incumbent: str | None, adopt: bool) -> None:
    """Entry point for the detached background process."""
    _, cfg = _effective_proving_config()
    _run_foreground(cfg, candidate, incumbent, adopt)


@prove.command()
def status() -> None:
    """Show the latest proving run and its per-class scorecard."""
    store = _run_store()
    record = store.latest_run()
    if record is None:
        console.print("No proving runs yet. Start one with [bold]nova prove run[/bold].")
        return
    _print_run(record)


@prove.command("list")
@click.option("-n", "--limit", default=20, type=int, show_default=True)
def list_cmd(limit: int) -> None:
    """List recent proving runs."""
    store = _run_store()
    runs = store.list_runs(limit=limit)
    if not runs:
        console.print("No proving runs yet. Start one with [bold]nova prove run[/bold].")
        return

    table = Table(title="Proving Runs")
    table.add_column("ID", style="cyan")
    table.add_column("Started", style="dim")
    table.add_column("Trigger")
    table.add_column("Status")
    table.add_column("Candidate")
    table.add_column("Incumbent")
    table.add_column("Winners", justify="right")

    for r in runs:
        winners = sum(
            1
            for v in (r.get("per_class") or {}).values()
            if v.get("winner") and v["winner"] == r.get("candidate")
        )
        table.add_row(
            r["id"],
            (r["started_at"] or "")[:19],
            r.get("trigger", ""),
            _status_color(r["status"]),
            r.get("candidate", ""),
            r.get("incumbent", "") or "—",
            str(winners),
        )
    console.print(table)


@prove.command()
def roster() -> None:
    """Show the current per-class adoption map (what the router would use)."""
    from nova_ai.learning.proving.adoption import load_policy_map

    policy_map = load_policy_map(_proving_root())
    if not policy_map:
        console.print(
            "No proven adoptions yet. Adopt one with [bold]nova prove adopt <run_id>[/bold]."
        )
        return

    table = Table(title="Proven Routing Map")
    table.add_column("Query Class", style="cyan")
    table.add_column("Model")
    table.add_column("Margin", justify="right")
    table.add_column("Run")
    table.add_column("Adopted", style="dim")
    for qclass in sorted(policy_map):
        entry = policy_map[qclass]
        table.add_row(
            qclass,
            entry.get("model", ""),
            f"{entry.get('margin', 0):+.4f}",
            entry.get("run_id", ""),
            (entry.get("adopted_at") or "")[:19],
        )
    console.print(table)
    console.print(
        "[dim]Note: the router serves these models only with "
        "[router] proving_adoption = true (or an equivalent engine config).[/dim]"
    )


@prove.command()
@click.argument("run_id")
@click.option(
    "--class",
    "classes",
    default=None,
    help="Comma-separated query classes to adopt (default: all candidate winners).",
)
def adopt(run_id: str, classes: str | None) -> None:
    """Adopt a completed run's winners into the routing map."""
    from nova_ai.learning.proving.adoption import adopt_winners

    store = _run_store()
    record = store.get_run(run_id)
    if record is None:
        console.print(f"[red]Unknown run:[/red] {run_id}")
        raise SystemExit(1)
    if record.get("status") != "completed":
        console.print(
            f"[red]Run {run_id} is {record.get('status')!r}; only completed runs "
            "can be adopted.[/red]"
        )
        raise SystemExit(1)

    per_class = record.get("per_class") or {}
    if classes:
        wanted = {c.strip() for c in classes.split(",") if c.strip()}
        per_class = {k: v for k, v in per_class.items() if k in wanted}
        missing = wanted - set(per_class)
        if missing:
            console.print(
                f"[yellow]Not in run {run_id}:[/yellow] {', '.join(sorted(missing))}"
            )

    _, cfg = _effective_proving_config()
    adopted = adopt_winners(
        run_id=run_id,
        per_class=per_class,
        min_margin=cfg.min_margin,
        proving_root=_proving_root(),
    )
    if adopted:
        store.finish_run(
            run_id,
            status="completed",
            samples=record.get("samples", 0),
            per_class=record.get("per_class") or {},
            adopted=adopted,
        )
        console.print(f"[green]Adopted {len(adopted)} class(es):[/green] {adopted}")
    else:
        console.print(
            "[yellow]Nothing to adopt[/yellow] — no class where the candidate "
            "won by at least the margin "
            f"({cfg.min_margin})."
        )


@prove.command()
@click.argument("query_class")
def revert(query_class: str) -> None:
    """Remove QUERY_CLASS from the routing map (undo an adoption)."""
    from nova_ai.learning.proving.adoption import revert_class

    if revert_class(query_class, proving_root=_proving_root()):
        console.print(f"[green]Reverted[/green] routing for class {query_class!r}.")
    else:
        console.print(f"[yellow]No adoption found for class[/yellow] {query_class!r}.")
        raise SystemExit(1)


@prove.command()
@click.option(
    "--prove",
    is_flag=True,
    default=False,
    help="Run the gauntlet for each newly detected model.",
)
@click.option("--foreground", is_flag=True, default=False, help="Run prove in-process.")
def watch(prove: bool, foreground: bool) -> None:
    """Check for newly pulled models (optionally prove them)."""
    from nova_ai.core.paths import get_config_dir
    from nova_ai.learning.proving.watcher import detect_new_models, list_local_models

    _, cfg = _effective_proving_config()
    root = _proving_root()
    models = list_local_models(load_config())
    new = detect_new_models(state_path=root / "known_models.json", models=models)

    if not new:
        console.print("[green]No new models since the last check.[/green]")
        return

    console.print(f"New model(s): [cyan]{', '.join(new)}[/cyan]")
    if not prove:
        console.print("Run [bold]nova prove watch --prove[/bold] to prove them.")
        return

    if not cfg.enabled:
        console.print(
            "[yellow]The proving ground is disabled[/yellow] — set "
            "[learning.proving] enabled = true first."
        )
        raise SystemExit(1)

    if foreground:
        from nova_ai.learning.proving.pipeline import run_proving
        from nova_ai.traces.store import TraceStore

        run_store = _run_store()
        for candidate in new:
            record = run_proving(
                candidate=candidate,
                trace_store=TraceStore(get_config_dir() / "traces.db"),
                config=cfg,
                run_store=run_store,
                proving_root=root,
                trigger="manual",
            )
            _print_run(record)
            if record.get("status") != "completed":
                raise SystemExit(1)
    else:
        _spawn_background(new[0], None, False)
        console.print(
            f"[green]Proving {new[0]} in the background.[/green] "
            f"({len(new) - 1} more queued for later checks)"
            if len(new) > 1
            else f"[green]Proving {new[0]} in the background.[/green]"
        )


def _status_color(status: str) -> str:
    colors = {
        "completed": "green",
        "failed": "red",
        "running": "cyan",
    }
    color = colors.get(status, "white")
    return f"[{color}]{status}[/{color}]"


def _print_run(record: dict) -> None:
    if not record:
        console.print("[red]Run record unavailable.[/red]")
        return
    table = Table(title=f"Proving Run {record['id']}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    table.add_row("Status", _status_color(record["status"]))
    table.add_row("Trigger", record.get("trigger", ""))
    table.add_row("Candidate", record.get("candidate", "—"))
    table.add_row("Incumbent", record.get("incumbent", "") or "—")
    table.add_row("Samples", str(record.get("samples", 0)))
    if record.get("error"):
        table.add_row("Error", str(record["error"]))
    console.print(table)

    per_class = record.get("per_class") or {}
    if per_class:
        scorecard = Table(title="Per-Query-Class Scorecard")
        scorecard.add_column("Class", style="cyan")
        scorecard.add_column("Candidate", justify="right")
        scorecard.add_column("Incumbent", justify="right")
        scorecard.add_column("Δ", justify="right")
        scorecard.add_column("Winner")
        for qclass in sorted(per_class):
            v = per_class[qclass]
            cand = v.get("candidate_acc")
            inc = v.get("incumbent_acc")
            delta = v.get("delta")
            winner = v.get("winner") or "—"
            color = (
                "green"
                if winner == record.get("candidate")
                else "red" if winner and winner != "—" else "dim"
            )
            scorecard.add_row(
                qclass,
                f"{cand:.0%}" if cand is not None else "—",
                f"{inc:.0%}" if inc is not None else "—",
                f"{delta:+.2f}" if delta is not None else "—",
                f"[{color}]{winner}[/{color}]",
            )
        console.print(scorecard)

    adopted = record.get("adopted") or {}
    if adopted:
        console.print(f"[green]Adopted:[/green] {adopted}")


__all__ = ["prove"]
