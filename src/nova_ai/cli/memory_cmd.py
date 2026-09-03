"""``nova memory`` — memory management subcommands."""

from __future__ import annotations

import time
from pathlib import Path

import click
from rich.console import Console
from rich.progress import track
from rich.table import Table

from nova_ai.core.config import load_config
from nova_ai.core.registry import MemoryRegistry
from nova_ai.tools.storage.chunking import ChunkConfig
from nova_ai.tools.storage.ingest import ingest_path


def _get_backend(backend_key: str | None = None):
    """Instantiate the configured (or overridden) memory backend."""
    config = load_config()
    key = backend_key or config.memory.default_backend

    # Ensure backends are registered
    import nova_ai.tools.storage  # noqa: F401

    if not MemoryRegistry.contains(key):
        raise click.ClickException(
            f"Memory backend '{key}' not found. "
            f"Available: {', '.join(MemoryRegistry.keys())}"
        )

    if key == "sqlite":
        return MemoryRegistry.create(key, db_path=config.memory.db_path)
    return MemoryRegistry.create(key)


@click.group()
def memory() -> None:
    """Manage the memory store."""


@memory.command()
@click.argument("path")
@click.option(
    "--backend",
    "-b",
    default=None,
    help="Override the default memory backend.",
)
@click.option(
    "--chunk-size",
    default=512,
    type=int,
    help="Chunk size in tokens.",
)
@click.option(
    "--chunk-overlap",
    default=64,
    type=int,
    help="Overlap between chunks in tokens.",
)
def index(
    path: str,
    backend: str | None,
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    """Index documents from a file or directory."""
    console = Console(stderr=True)
    target = Path(path)

    if not target.exists():
        console.print(f"[red]Path not found:[/red] {path}")
        raise SystemExit(1)

    t0 = time.time()
    cfg = ChunkConfig(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    console.print(f"[cyan]Indexing[/cyan] {path} ...")
    chunks = ingest_path(target, config=cfg)

    if not chunks:
        console.print("[yellow]No indexable content found.[/yellow]")
        return

    mem = _get_backend(backend)
    try:
        for chunk in track(chunks, description="Storing chunks...", console=console):
            mem.store(
                chunk.content,
                source=chunk.source,
                metadata={
                    "offset": chunk.offset,
                    "index": chunk.index,
                },
            )
    finally:
        if hasattr(mem, "close"):
            mem.close()

    elapsed = time.time() - t0
    sources = {c.source for c in chunks}
    console.print(
        f"[green]Indexed {len(chunks)} chunks "
        f"from {len(sources)} file(s) "
        f"in {elapsed:.1f}s.[/green]"
    )


@memory.command()
@click.argument("query", nargs=-1, required=True)
@click.option(
    "--top-k",
    "-k",
    default=5,
    type=int,
    help="Number of results to return.",
)
@click.option(
    "--backend",
    "-b",
    default=None,
    help="Override the default memory backend.",
)
def search(
    query: tuple[str, ...],
    top_k: int,
    backend: str | None,
) -> None:
    """Search the memory store."""
    console = Console()
    query_text = " ".join(query)

    mem = _get_backend(backend)
    try:
        results = mem.retrieve(query_text, top_k=top_k)
    finally:
        if hasattr(mem, "close"):
            mem.close()

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Search: {query_text}")
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", width=8)
    table.add_column("Source", style="cyan")
    table.add_column("Content")

    for i, r in enumerate(results, 1):
        # Truncate content for display
        preview = r.content[:200]
        if len(r.content) > 200:
            preview += "..."
        table.add_row(
            str(i),
            f"{r.score:.4f}",
            r.source or "-",
            preview,
        )

    console.print(table)


@memory.command()
@click.option(
    "--backend",
    "-b",
    default=None,
    help="Override the default memory backend.",
)
def stats(backend: str | None) -> None:
    """Show memory store statistics."""
    console = Console()

    mem = _get_backend(backend)
    try:
        count = 0
        if hasattr(mem, "count"):
            count = mem.count()

        table = Table(title="Memory Statistics")
        table.add_column("Property", style="cyan")
        table.add_column("Value")
        table.add_row("Backend", mem.backend_id)
        table.add_row("Documents", str(count))

        if hasattr(mem, "_db_path"):
            db_path = Path(mem._db_path)
            if db_path.exists():
                size_kb = db_path.stat().st_size / 1024
                table.add_row(
                    "Database size",
                    f"{size_kb:.1f} KB",
                )
            table.add_row("Database path", str(db_path))

        console.print(table)
    finally:
        if hasattr(mem, "close"):
            mem.close()


# ---------------------------------------------------------------------------
# ``nova memory consolidate`` — the memory sleep cycle
# ---------------------------------------------------------------------------


def _consolidation_root() -> Path:
    from nova_ai.core.paths import get_config_dir

    return get_config_dir() / "learning" / "consolidation"


def _fact_store():
    from nova_ai.memory.consolidation.store import FactStore

    return FactStore(_consolidation_root() / "facts.db")


def _run_store():
    from nova_ai.memory.consolidation.store import ConsolidationRunStore

    return ConsolidationRunStore(_consolidation_root() / "runs.db")


def _effective_consolidation_config():
    learning_cfg = load_config().learning
    return learning_cfg.consolidation


@memory.command("consolidate")
@click.argument(
    "action",
    type=click.Choice(["run", "status", "facts", "forget"]),
)
@click.argument("extra", required=False)
@click.option(
    "--foreground",
    is_flag=True,
    default=False,
    help="Run in the foreground (default: background).",
)
@click.option("-n", "--limit", default=20, help="Rows for `facts`.")
def consolidate(action: str, extra: str | None, foreground: bool, limit: int) -> None:
    """Memory sleep cycle: run | status | facts | forget FACT_ID."""
    console = Console()

    if action == "run":
        cfg = _effective_consolidation_config()
        if not cfg.enabled:
            console.print(
                "[red]learning.consolidation.enabled is false; "
                "enable it in ~/.nova_ai/config.toml first.[/red]"
            )
            raise SystemExit(1)
        if foreground:
            summary = _run_foreground(cfg)
            console.print(f"[green]{summary}[/green]")
            return
        _spawn_background()
        console.print("[green]Consolidation started in the background.[/green]")
        console.print("Check progress: [bold]nova memory consolidate status[/bold]")
        return

    if action == "status":
        store = _run_store()
        try:
            run = store.latest_run()
            if run is None:
                console.print("[yellow]No consolidation runs yet.[/yellow]")
                return
            console.print(f"[bold]{run['id']}[/bold] — {run['status']}")
            console.print(f"  Trigger: {run['trigger']}")
            if run.get("summary"):
                console.print(f"  Summary: {run['summary']}")
            if run.get("error"):
                console.print(f"  [red]Error: {run['error']}[/red]")
        finally:
            store.close()
        return

    if action == "facts":
        store = _fact_store()
        try:
            facts = store.list_facts(limit=limit)
            if not facts:
                console.print("[yellow]No facts distilled yet.[/yellow]")
                return
            table = Table(title="Consolidated Facts")
            table.add_column("ID", style="dim")
            table.add_column("Conf.", style="cyan")
            table.add_column("Topic")
            table.add_column("Fact")
            for fact in facts:
                table.add_row(
                    fact["id"],
                    f"{fact['confidence']:.2f}",
                    fact["topic"] or "-",
                    fact["content"][:80],
                )
            console.print(table)
        finally:
            store.close()
        return

    # action == "forget"
    if not extra:
        console.print("[red]Usage: nova memory consolidate forget FACT_ID[/red]")
        raise SystemExit(1)
    store = _fact_store()
    try:
        updated = store.set_status(extra, "forgotten")
        if updated:
            console.print(f"[green]Fact {extra} forgotten.[/green]")
        else:
            console.print(f"[yellow]Fact '{extra}' not found.[/yellow]")
            raise SystemExit(1)
    finally:
        store.close()


def _run_foreground(cfg):
    from nova_ai.core.paths import get_config_dir
    from nova_ai.memory.consolidation.pipeline import run_consolidation
    from nova_ai.traces.store import TraceStore

    trace_store = TraceStore(get_config_dir() / "traces.db")
    fact_store = _fact_store()
    run_store = _run_store()
    try:
        return run_consolidation(
            trace_store=trace_store,
            fact_store=fact_store,
            config=cfg,
            run_store=run_store,
            trigger="manual",
        )
    finally:
        trace_store.close()
        fact_store.close()
        run_store.close()


def _spawn_background() -> None:
    """Launch a detached child process running the pipeline."""
    import os
    import subprocess
    import sys

    from nova_ai.core.config import DEFAULT_CONFIG_DIR

    log_path = _consolidation_root() / "last_run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    python = sys.executable
    script = (
        "from nova_ai.cli.memory_cmd import _run_background_entry;"
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
            env={**os.environ, "NOVA_CONSOLIDATION_BACKGROUND": "1"},
            cwd=str(DEFAULT_CONFIG_DIR),
        )


def _run_background_entry() -> None:
    """Entry point for the detached background process."""
    cfg = _effective_consolidation_config()
    _run_foreground(cfg)
