"""``nova oracle`` — the Fleet Oracle: ask the fleet, not the vendor.

Aggregates anonymized hardware + per-model performance reports from
NOVA machines. ``export`` previews what would be shared (the only data
that ever leaves the machine), ``push`` publishes it (opt-in via
``learning.fleet.share_reports``), ``ask`` answers a question from the
pooled dataset locally.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from nova_ai.core.config import load_config

console = Console()


@click.group()
def oracle() -> None:
    """Fleet Oracle: pooled, anonymized performance answers."""


def _fleet_cfg():
    return load_config().learning.fleet


def _build_report():
    from nova_ai.learning.fleet.report import build_report

    return build_report(config_obj=load_config())


def _print_report(report: dict) -> None:
    console.print(f"[bold]Report {report['report_id']}[/bold] "
                  f"(schema v{report['schema_version']}, window "
                  f"{report['window_days']} days)")
    hw = report["hardware"]
    gpu = hw.get("gpu") or {}
    console.print(
        f"  Hardware: {hw.get('platform', '?')} / "
        f"{hw.get('cpu_count', '?')} cores / {hw.get('ram_gb', '?')} GB RAM"
        + (f" / {gpu.get('name', '?')} ({gpu.get('vram_gb', '?')} GB)" if gpu else "")
    )
    table = Table(title="Models (k-anonymized)")
    table.add_column("Model", style="cyan")
    table.add_column("Engine")
    table.add_column("Calls", justify="right")
    table.add_column("Avg lat (s)", justify="right")
    table.add_column("Tok/s", justify="right")
    table.add_column("Tok/J", justify="right")
    for m in report["models"]:
        table.add_row(
            m["model_id"],
            m.get("engine", ""),
            str(m["call_count"]),
            f"{m['avg_latency_s']:.2f}",
            f"{m['avg_throughput_tok_per_sec']:.1f}",
            f"{m['avg_tokens_per_joule']:.1f}",
        )
    if report["models"]:
        console.print(table)
    else:
        console.print(
            "[yellow]No models pass the k-anonymity threshold "
            "(min_calls_per_model). Nothing to share yet.[/yellow]"
        )


@oracle.command("export")
@click.option(
    "-o",
    "--out",
    "out_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Write the report JSON to this path instead of printing it.",
)
def export_cmd(out_path: Optional[Path]) -> None:
    """Build the anonymized report and show (or save) it."""
    report = _build_report()
    if out_path is not None:
        out_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        console.print(f"[green]Report written to[/green] {out_path}")
        return
    _print_report(report)
    console.print(
        "[dim]This is the exact payload sharing would publish — a fixed "
        "field list: hardware shape and per-model averages. No prompts, "
        "content, paths, or IDs.[/dim]"
    )


@oracle.command()
def push() -> None:
    """Push the anonymized report to the shared dataset repo."""
    from nova_ai.learning.fleet.push import FleetPushError, push_report

    cfg = _fleet_cfg()
    if not cfg.share_reports:
        console.print(
            "[red]Sharing is off.[/red] Set [bold]learning.fleet.share_reports "
            "= true[/bold] in ~/.nova_ai/config.toml to opt in."
        )
        raise SystemExit(1)
    if not cfg.dataset_repo:
        console.print(
            "[red]No dataset repo configured.[/red] Set "
            "[bold]learning.fleet.dataset_repo[/bold] to a git URL."
        )
        raise SystemExit(1)

    report = _build_report()
    if not report["models"]:
        console.print(
            "[yellow]Report has no models above the k-anonymity threshold — "
            "nothing meaningful to share.[/yellow]"
        )
        raise SystemExit(1)
    try:
        path = push_report(report, cfg.dataset_repo, cache_dir=cfg.cache_dir or None)
    except (FleetPushError, ValueError) as exc:
        console.print(f"[red]Push failed:[/red] {exc}")
        raise SystemExit(1)
    console.print(f"[green]Pushed[/green] {path}")


@oracle.command()
@click.argument("question")
@click.option(
    "--repo",
    "repo_url",
    default=None,
    help="Dataset repo override (default: learning.fleet.dataset_repo).",
)
def ask(question: str, repo_url: Optional[str]) -> None:
    """Ask the fleet, e.g. "best 8B model for code on a 4090?"."""
    from nova_ai.learning.fleet.oracle import query_fleet
    from nova_ai.learning.fleet.push import FleetPushError, load_reports

    cfg = _fleet_cfg()
    repo = repo_url or cfg.dataset_repo
    if not repo:
        console.print(
            "[red]No dataset repo configured.[/red] Set "
            "[bold]learning.fleet.dataset_repo[/bold] to a git URL."
        )
        raise SystemExit(1)
    try:
        reports = load_reports(repo, cache_dir=cfg.cache_dir or None)
    except (FleetPushError, ValueError) as exc:
        console.print(f"[red]Could not load the fleet dataset:[/red] {exc}")
        raise SystemExit(1)
    if not reports:
        console.print(
            "[yellow]The dataset has no reports yet — be the first to "
            "export one (nova oracle export).[/yellow]"
        )
        raise SystemExit(1)

    answer = query_fleet(question, reports)
    console.print(f"[bold]{answer.headline}[/bold]")
    console.print(
        f"[dim]intent={answer.intent}"
        + (f" bucket={answer.bucket_label}" if answer.bucket_label else "")
        + (f" model={answer.matched_model}" if answer.matched_model else "")
        + f" | {answer.reports_used} report(s)[/dim]"
    )
    for bucket in answer.buckets:
        table = Table(title=bucket["label"])
        table.add_column("Model", style="cyan")
        table.add_column("Machines", justify="right")
        table.add_column("Calls", justify="right")
        table.add_column("Avg lat (s)", justify="right")
        table.add_column("Tok/s", justify="right")
        table.add_column("Tok/J", justify="right")
        for row in bucket["rows"]:
            table.add_row(
                row["model"],
                str(row["machines"]),
                str(row["call_count"]),
                f"{row['avg_latency_s']:.2f}",
                f"{row['avg_throughput_tok_per_sec']:.1f}",
                f"{row['avg_tokens_per_joule']:.1f}",
            )
        console.print(table)


@oracle.command()
def status() -> None:
    """Show fleet config and local dataset state."""
    from nova_ai.learning.fleet.push import default_cache_dir

    cfg = _fleet_cfg()
    table = Table(title="Fleet Oracle")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    table.add_row(
        "share_reports",
        "[green]true[/green]" if cfg.share_reports else "false (opt in to push)",
    )
    table.add_row("dataset_repo", cfg.dataset_repo or "—")
    table.add_row("min_calls_per_model", str(cfg.min_calls_per_model))
    table.add_row("since_days", str(cfg.since_days))
    cache = Path(cfg.cache_dir) if cfg.cache_dir else default_cache_dir()
    table.add_row("cache_dir", str(cache))
    console.print(table)

    reports_dir = cache / "reports"
    count = len(list(reports_dir.glob("*.json"))) if reports_dir.is_dir() else 0
    console.print(f"Local dataset copy: {count} report(s)")


__all__ = ["oracle"]
