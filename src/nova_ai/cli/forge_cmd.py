"""``nova forge`` — the Skill Foundry: turn repeated tool runs into skills.

Shares one pipeline (``learning.skillforge.pipeline.run_skillforge``) with
the scheduler task. The forge only *proposes*; ``nova forge adopt`` is the
single mutation that installs a skill, and ``nova forge revert`` undoes it.
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


def _skills_root() -> Path:
    from nova_ai.core.paths import get_config_dir

    return get_config_dir() / "skills"


def _forge_root() -> Path:
    from nova_ai.core.paths import get_config_dir

    return get_config_dir() / "learning" / "skillforge"


def _run_store():
    from nova_ai.learning.skillforge.store import SkillForgeRunStore

    return SkillForgeRunStore(_forge_root() / "runs.db")


def _effective_skillforge_config():
    learning_cfg = load_config().learning
    return learning_cfg.skillforge


@click.group()
def forge() -> None:
    """Forge skills from your repeated multi-step tool workflows."""


@forge.command()
@click.option(
    "--foreground",
    is_flag=True,
    default=False,
    help="Run in the foreground (default: background).",
)
def run(foreground: bool) -> None:
    """Mine patterns and forge candidate skills."""
    cfg = _effective_skillforge_config()
    if not cfg.enabled:
        console.print(
            "[red]learning.skillforge.enabled is false; "
            "enable it in ~/.nova_ai/config.toml first.[/red]"
        )
        raise SystemExit(1)

    store = _run_store()
    store.close()
    if foreground:
        summary = _run_foreground(cfg)
        _print_summary(summary)
        raise SystemExit(0 if summary.get("status") in ("completed", "skipped") else 1)

    _spawn_background()
    console.print("[green]Forge run started in the background.[/green]")
    console.print("Check progress: [bold]nova forge status[/bold]")


def _run_foreground(cfg):
    from nova_ai.core.paths import get_config_dir
    from nova_ai.learning.skillforge.pipeline import run_skillforge
    from nova_ai.traces.store import TraceStore

    trace_store = TraceStore(get_config_dir() / "traces.db")
    run_store = _run_store()
    tool_executor = _build_tool_executor()
    try:
        return run_skillforge(
            trace_store=trace_store,
            config=cfg,
            run_store=run_store,
            skills_root=_skills_root(),
            tool_executor=tool_executor,
            trigger="manual",
        )
    finally:
        trace_store.close()
        run_store.close()


def _build_tool_executor():
    """Build a ToolExecutor over all registered tools."""
    from nova_ai.core.registry import ToolRegistry
    from nova_ai.tools._stubs import ToolExecutor

    tools = []
    for name in ToolRegistry.keys():
        try:
            tools.append(ToolRegistry.create(name))
        except Exception:
            continue
    return ToolExecutor(tools)


def _spawn_background() -> None:
    """Launch a detached child process running the pipeline."""
    from nova_ai.core.config import DEFAULT_CONFIG_DIR

    log_path = _forge_root() / "last_run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    python = sys.executable
    script = (
        "from nova_ai.cli.forge_cmd import _run_background_entry;"
        "_run_background_entry()"
    )
    creationflags = 0
    close_fds = True
    if sys.platform == "win32":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        close_fds = False

    with open(log_path, "ab") as log_f:
        subprocess.Popen(
            [python, "-c", script],
            stdout=log_f,
            stderr=log_f,
            stdin=subprocess.DEVNULL,
            close_fds=close_fds,
            creationflags=creationflags,
            start_new_session=sys.platform != "win32",
            env={**os.environ, "NOVA_SKILLFORGE_BACKGROUND": "1"},
            cwd=str(DEFAULT_CONFIG_DIR),
        )


def _run_background_entry() -> None:
    """Entry point for the detached background process."""
    cfg = _effective_skillforge_config()
    _run_foreground(cfg)


@forge.command()
def status() -> None:
    """Show the latest forge run and its gauntlet report."""
    store = _run_store()
    try:
        record = store.latest_run()
        if record is None:
            console.print("No forge runs yet. Start one with [bold]nova forge run[/bold].")
            return
        _print_run(record)
    finally:
        store.close()


@forge.command("list")
@click.option("-n", "--limit", default=20, type=int, show_default=True)
def list_cmd(limit: int) -> None:
    """List candidate skills (passed/failed/synthesis_failed)."""
    store = _run_store()
    try:
        runs = store.list_candidate_runs(limit=limit)
        if not runs:
            console.print(
                "No forged candidates yet. Run [bold]nova forge run[/bold] first."
            )
            return
        table = Table(title="Forged Skill Candidates")
        table.add_column("Run", style="cyan")
        table.add_column("Skill")
        table.add_column("Seen", justify="right")
        table.add_column("Sequence")
        table.add_column("Status")
        for r in runs:
            table.add_row(
                r["id"],
                r.get("skill_name", ""),
                str(r.get("pattern_count", 0)),
                " -> ".join(r.get("sequence", []))[:40],
                r.get("status", ""),
            )
        console.print(table)
    finally:
        store.close()


@forge.command()
@click.argument("run_id")
def adopt(run_id: str) -> None:
    """Adopt a passed candidate — install it into ~/.nova_ai/skills/generated/."""
    from nova_ai.learning.skillforge.adoption import adopt_skill

    store = _run_store()
    try:
        record = store.get_run(run_id)
        if record is None:
            console.print(f"[red]Unknown run:[/red] {run_id}")
            raise SystemExit(1)
        gauntlet = record.get("gauntlet") or {}
        if record.get("status") != "passed":
            console.print(
                f"[red]Run {run_id} is {record.get('status')!r}; only passed "
                "candidates can be adopted.[/red]"
            )
            raise SystemExit(1)
        manifest = gauntlet.get("manifest")
        if manifest is None:
            console.print(
                "[yellow]No manifest recorded for this run "
                "(older format). Re-run the forge first.[/yellow]"
            )
            raise SystemExit(1)
        from nova_ai.skills.types import SkillManifest, SkillStep

        rebuilt = SkillManifest(
            name=manifest["name"],
            version=manifest.get("version", "0.1.0"),
            description=manifest.get("description", ""),
            author=manifest.get("author", ""),
            steps=[
                SkillStep(
                    tool_name=s.get("tool_name", ""),
                    skill_name=s.get("skill_name", ""),
                    arguments_template=s.get("arguments_template", "{}"),
                    output_key=s.get("output_key", ""),
                )
                for s in manifest.get("steps", [])
            ],
            required_capabilities=manifest.get("required_capabilities", []),
            tags=manifest.get("tags", []),
        )
        try:
            path = adopt_skill(
                rebuilt,
                run_id=run_id,
                gauntlet=gauntlet,
                pattern_count=record.get("pattern_count", 0),
                skills_root=_skills_root(),
            )
        except ValueError as exc:
            console.print(f"[red]Adoption refused:[/red] {exc}")
            raise SystemExit(1)
        console.print(f"[green]Adopted skill[/green] {rebuilt.name!r} -> {path}")
        console.print(
            "[dim]It will be discovered on the next skill scan "
            "(restart the daemon or the desktop app).[/dim]"
        )
    finally:
        store.close()


@forge.command()
@click.argument("run_id")
def reject(run_id: str) -> None:
    """Mark a candidate rejected (keeps the record for the audit trail)."""
    store = _run_store()
    try:
        record = store.get_run(run_id)
        if record is None:
            console.print(f"[red]Unknown run:[/red] {run_id}")
            raise SystemExit(1)
        store.finish_run(
            run_id,
            status="rejected",
            skill_name=record.get("skill_name", ""),
            pattern_count=record.get("pattern_count", 0),
            sequence=record.get("sequence", []),
            gauntlet=record.get("gauntlet") or {},
        )
        console.print(f"[green]Rejected[/green] candidate {run_id}.")
    finally:
        store.close()


@forge.command()
@click.argument("skill_name")
def revert(skill_name: str) -> None:
    """Uninstall an adopted skill (deletes generated/<name>)."""
    from nova_ai.learning.skillforge.adoption import revert_skill

    if revert_skill(skill_name, skills_root=_skills_root()):
        console.print(f"[green]Reverted[/green] skill {skill_name!r}.")
    else:
        console.print(f"[yellow]No adopted skill found named[/yellow] {skill_name!r}.")
        raise SystemExit(1)


def _print_summary(summary: dict) -> None:
    status = summary.get("status", "?")
    color = "green" if status == "completed" else "yellow" if status == "skipped" else "red"
    console.print(f"[{color}]Forge run: {status}[/{color}]")
    if summary.get("reason"):
        console.print(f"  Reason: {summary['reason']}")
    if summary.get("error"):
        console.print(f"  [red]Error: {summary['error']}[/red]")
    for skill in summary.get("skills", []):
        gates = ", ".join(
            f"{g['name']}={'PASS' if g['passed'] else 'FAIL'}"
            for g in skill.get("gauntlet", {}).get("gates", [])
        )
        console.print(
            f"  - {skill['skill_name']}: {skill['status']}"
            + (" (adopted)" if skill.get("adopted") else "")
            + f"  [{gates}]"
        )


def _print_run(record: dict) -> None:
    table = Table(title=f"Forge Run {record['id']}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Status", record.get("status", ""))
    table.add_row("Trigger", record.get("trigger", ""))
    table.add_row("Skill", record.get("skill_name", "") or "—")
    table.add_row("Pattern count", str(record.get("pattern_count", 0)))
    table.add_row(
        "Sequence", " -> ".join(record.get("sequence", [])) or "—"
    )
    if record.get("error"):
        table.add_row("Error", str(record["error"]))
    console.print(table)

    gauntlet = record.get("gauntlet") or {}
    gates = gauntlet.get("gates") or []
    if gates:
        gate_table = Table(title="Gauntlet")
        gate_table.add_column("Gate", style="cyan")
        gate_table.add_column("Result")
        gate_table.add_column("Detail")
        for g in gates:
            gate_table.add_row(
                g.get("name", "?"),
                "[green]PASS[/green]" if g.get("passed") else "[red]FAIL[/red]",
                (g.get("detail", "") or "")[:100],
            )
        console.print(gate_table)


__all__ = ["forge"]
