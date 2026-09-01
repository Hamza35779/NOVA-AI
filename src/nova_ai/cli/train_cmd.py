"""``nova train`` — self-training pipeline: mine traces → LoRA → deploy.

Turns recorded interaction traces into a fine-tuned adapter. The pipeline
is shared with the scheduler (cron) trigger and the auto-trigger; the CLI
adds manual runs, inspection, and promotion of pending adapters.

Safety: weight updates are the most invasive edit class, so unless
``[learning.training] auto_apply = true`` a finished run lands in
``pending_review`` and only ``nova train deploy`` activates it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from nova_ai.core.config import load_config

console = Console()


def _training_root() -> Path:
    from nova_ai.core.paths import get_config_dir

    return get_config_dir() / "learning" / "training"


def _run_store():
    from nova_ai.learning.training.store import TrainingRunStore

    return TrainingRunStore(_training_root() / "runs.db")


def _effective_training_config():
    learning_cfg = load_config().learning
    return learning_cfg, learning_cfg.training_effective


@click.group()
def train() -> None:
    """Self-training: fine-tune a model from your own usage traces."""


@train.command()
@click.option(
    "--foreground",
    is_flag=True,
    default=False,
    help="Run in the foreground and stream progress (default: background).",
)
@click.option("--base-model", default=None, help="Base model (HF id or local path).")
def run(foreground: bool, base_model: str | None) -> None:
    """Mine traces, train a LoRA adapter, and deploy per config."""
    learning_cfg, cfg = _effective_training_config()
    if not cfg.enabled:
        console.print(
            "[yellow]Self-training is disabled.[/yellow] Enable it with:\n\n"
            "  [learning.training]\n"
            '  enabled = true\n\n'
            "in ~/.nova_ai/config.toml"
        )
        raise SystemExit(1)

    store = _run_store()
    if store.is_running():
        console.print("[yellow]A training run is already in flight.[/yellow]")
        console.print("Check progress: [bold]nova train status[/bold]")
        raise SystemExit(1)

    if foreground:
        record = _run_foreground(learning_cfg, cfg, base_model)
        _print_run(record)
        raise SystemExit(0 if record.get("status") in ("completed", "pending_review") else 1)

    # Background: spawn a detached python process running the same pipeline.
    _spawn_background(base_model)
    console.print("[green]Training started in the background.[/green]")
    console.print("Check progress: [bold]nova train status[/bold]")


def _run_foreground(learning_cfg, cfg, base_model: str | None):
    from nova_ai.core.paths import get_config_dir
    from nova_ai.learning.training.pipeline import run_training
    from nova_ai.traces.store import TraceStore

    trace_store = TraceStore(get_config_dir() / "traces.db")
    return run_training(
        trace_store=trace_store,
        config=cfg,
        run_store=_run_store(),
        training_root=_training_root(),
        trigger="manual",
        base_model=base_model,
        min_improvement=learning_cfg.min_improvement,
    )


def _spawn_background(base_model: str | None) -> None:
    """Launch a detached child process running the pipeline.

    Windows-safe: DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, no console
    inheritance, output redirected to a log file under the training root.
    """
    from nova_ai.core.config import DEFAULT_CONFIG_DIR

    log_path = _training_root() / "last_run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    python = sys.executable
    script = (
        "from nova_ai.cli.train_cmd import _run_background_entry;"
        f"_run_background_entry({base_model!r})"
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
            env={**os.environ, "NOVA_TRAINING_BACKGROUND": "1"},
            cwd=str(DEFAULT_CONFIG_DIR),
        )


def _run_background_entry(base_model: str | None) -> None:
    """Entry point for the detached background process."""
    learning_cfg, cfg = _effective_training_config()
    _run_foreground(learning_cfg, cfg, base_model)


@train.command()
def status() -> None:
    """Show the latest training run."""
    store = _run_store()
    record = store.latest_run()
    if record is None:
        console.print("No training runs yet. Start one with [bold]nova train run[/bold].")
        return
    _print_run(record)


@train.command("list")
@click.option("-n", "--limit", default=20, type=int, help="Number of runs to show.")
def list_cmd(limit: int) -> None:
    """List recent training runs."""
    store = _run_store()
    runs = store.list_runs(limit=limit)
    if not runs:
        console.print("No training runs yet. Start one with [bold]nova train run[/bold].")
        return

    table = Table(title="Training Runs")
    table.add_column("ID", style="cyan")
    table.add_column("Started", style="dim")
    table.add_column("Trigger")
    table.add_column("Status")
    table.add_column("Pairs", justify="right")
    table.add_column("Avg Loss", justify="right")
    table.add_column("Δ Bench", justify="right")

    for r in runs:
        delta = r.get("benchmark_delta")
        table.add_row(
            r["id"],
            (r["started_at"] or "")[:19],
            r.get("trigger", ""),
            _status_color(r["status"]),
            str(r.get("pairs", 0)),
            f"{r['avg_loss']:.4f}" if r.get("avg_loss") is not None else "—",
            f"{delta:+.4f}" if delta is not None else "—",
        )
    console.print(table)


@train.command()
@click.argument("adapter_name")
@click.option(
    "--target",
    type=click.Choice(["adapter", "ollama", "llamacpp"]),
    multiple=True,
    default=("adapter",),
    show_default=True,
    help="Deployment target(s); repeatable.",
)
def deploy_cmd(adapter_name: str, target: tuple[str, ...]) -> None:
    """Promote and deploy a pending adapter (manual review path).

    ADAPTER_NAME is the run id (see `nova train list`).
    """
    from nova_ai.learning.training.deploy import deploy
    from nova_ai.learning.training.pipeline import promote_adapter

    store = _run_store()
    record = store.get_run(adapter_name)
    if record is None:
        console.print(f"[red]Unknown run:[/red] {adapter_name}")
        raise SystemExit(1)

    adapter_path = record.get("adapter_path")
    if not adapter_path or not Path(adapter_path).exists():
        console.print(f"[red]Adapter missing:[/red] {adapter_path}")
        raise SystemExit(1)

    _, cfg = _effective_training_config()
    report = deploy(
        Path(adapter_path),
        targets=list(target),
        base_model=record.get("base_model") or None,
        tag_prefix=cfg.ollama_tag_prefix,
        gguf_script=cfg.llamacpp_gguf_script,
    )

    # Manual promotion counts as review: pending_review → completed.
    from nova_ai.learning.training.pipeline import active_adapter_path

    promote_adapter(
        Path(adapter_path),
        training_root=_training_root(),
        base_model=record.get("base_model") or "",
        run_id=adapter_name,
    )
    if store.get_run(adapter_name) and record.get("status") == "pending_review":
        record["status"] = "completed"
        store.finish_run(
            adapter_name,
            status="completed",
            pairs=record.get("pairs", 0),
            avg_loss=record.get("avg_loss"),
            adapter_path=adapter_path,
            deploy_results=report.to_list(),
        )

    for result in report.results:
        mark = "[green]✓[/green]" if result.ok else "[red]✗[/red]"
        console.print(f"{mark} {result.target}: {result.detail}")

    active = active_adapter_path(_training_root())
    if active:
        console.print(f"\nActive adapter: [bold]{active}[/bold]")


@train.command("export-traces")
@click.option(
    "--out",
    "-o",
    "out_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("pairs.jsonl"),
    show_default=True,
    help="Output JSONL file.",
)
@click.option("--min-quality", default=0.7, type=float, show_default=True)
@click.option("--agent", default=None, help="Filter to one agent type.")
def export_traces(out_path: Path, min_quality: float, agent: str | None) -> None:
    """Export mined SFT pairs to JSONL for external training runs.

    Each line: {\"input\", \"output\", \"query_class\", \"model\", \"feedback\"}.
    The portable form of your training data — take it to any trainer,
    cloud or local.
    """
    from nova_ai.core.paths import get_config_dir
    from nova_ai.learning.training.data import TrainingDataMiner
    from nova_ai.traces.store import TraceStore

    trace_store = TraceStore(get_config_dir() / "traces.db")
    miner = TrainingDataMiner(trace_store, min_quality=min_quality)
    pairs = miner.extract_sft_pairs(agent=agent)

    with open(out_path, "w", encoding="utf-8") as f:
        for pair in pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    console.print(
        f"[green]Exported {len(pairs)} SFT pairs[/green] → {out_path}"
    )
    if not pairs:
        console.print(
            "[dim]No qualifying traces yet — use NOVA and rate responses "
            "(nova feedback) to build training data.[/dim]"
        )


def _status_color(status: str) -> str:
    colors = {
        "completed": "green",
        "pending_review": "yellow",
        "rolled_back": "red",
        "failed": "red",
        "running": "cyan",
    }
    color = colors.get(status, "white")
    return f"[{color}]{status}[/{color}]"


def _print_run(record: dict) -> None:
    if not record:
        console.print("[red]Run record unavailable.[/red]")
        return
    table = Table(title=f"Training Run {record['id']}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    table.add_row("Status", _status_color(record["status"]))
    table.add_row("Trigger", record.get("trigger", ""))
    table.add_row("Base model", record.get("base_model", "—"))
    table.add_row("Pairs", str(record.get("pairs", 0)))
    if record.get("avg_loss") is not None:
        table.add_row("Avg loss", f"{record['avg_loss']:.4f}")
    if record.get("adapter_path"):
        table.add_row("Adapter", record["adapter_path"])
    if record.get("benchmark_delta") is not None:
        table.add_row(
            "Benchmark Δ",
            f"{record['benchmark_before']:.4f} → "
            f"{record['benchmark_after']:.4f} "
            f"(Δ {record['benchmark_delta']:+.4f})",
        )
    if record.get("error"):
        table.add_row("Error", str(record["error"]))
    for dr in record.get("deploy_results", []):
        mark = "✓" if dr["ok"] else "✗"
        table.add_row(f"Deploy: {dr['target']}", f"{mark} {dr['detail']}")
    console.print(table)


__all__ = ["train"]
