"""``nova model`` — model management subcommands."""

from __future__ import annotations

import logging
import os
import subprocess
import sys

import click
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nova_ai.core.config import load_config
from nova_ai.core.registry import ModelRegistry
from nova_ai.core.utils import soft_fail
from nova_ai.engine import discover_engines, discover_models
from nova_ai.engine.gguf import GGUF_CATALOG, download_gguf_model
from nova_ai.intelligence import merge_discovered_models, register_builtin_models
from nova_ai.intelligence.model_catalog import BUILTIN_MODELS

logger = logging.getLogger(__name__)


@click.group()
def model() -> None:
    """Manage language models."""


@model.command("list")
def list_models() -> None:
    """List available models from running engines."""
    console = Console()
    config = load_config()
    register_builtin_models()

    engines = discover_engines(config)
    if not engines:
        console.print(
            "[yellow]No inference engines detected.[/yellow]\n"
            "Start an engine (e.g. [cyan]ollama serve[/cyan]) and try again."
        )
        return

    all_models = discover_models(engines)
    for ek, model_ids in all_models.items():
        merge_discovered_models(ek, model_ids)

    table = Table(title="Available Models")
    table.add_column("Engine", style="cyan")
    table.add_column("Model", style="green")
    table.add_column("Params", justify="right")
    table.add_column("Active", justify="right")
    table.add_column("Context", justify="right")
    table.add_column("VRAM", justify="right")
    table.add_column("Arch", style="dim")

    for engine_key, model_ids in all_models.items():
        for mid in model_ids:
            try:
                spec = ModelRegistry.get(mid)
                params = f"{spec.parameter_count_b}B" if spec.parameter_count_b else "-"
                active = (
                    f"{spec.active_parameter_count_b}B"
                    if spec.active_parameter_count_b
                    else "-"
                )
                ctx = f"{spec.context_length:,}" if spec.context_length else "-"
                vram = f"{spec.min_vram_gb}GB" if spec.min_vram_gb else "-"
                arch = spec.metadata.get("architecture", "-")
            except KeyError:
                params = "-"
                active = "-"
                ctx = "-"
                vram = "-"
                arch = "-"
            table.add_row(engine_key, mid, params, active, ctx, vram, arch)

    console.print(table)


@model.command()
@click.argument("model_name")
def info(model_name: str) -> None:
    """Show details for a model."""
    console = Console()
    register_builtin_models()

    # Also try discovering from running engines
    config = load_config()
    engines = discover_engines(config)
    all_models = discover_models(engines)
    for ek, model_ids in all_models.items():
        merge_discovered_models(ek, model_ids)

    if not ModelRegistry.contains(model_name):
        console.print(f"[red]Model not found:[/red] {model_name}")
        sys.exit(1)

    spec = ModelRegistry.get(model_name)
    params = f"{spec.parameter_count_b}B" if spec.parameter_count_b else "unknown"
    active = (
        f"{spec.active_parameter_count_b}B" if spec.active_parameter_count_b else "-"
    )
    ctx_len = f"{spec.context_length:,}" if spec.context_length else "unknown"
    vram = f"{spec.min_vram_gb}GB" if spec.min_vram_gb else "-"
    engines_str = ", ".join(spec.supported_engines) if spec.supported_engines else "-"
    provider = spec.provider or "-"
    api_key = "required" if spec.requires_api_key else "not required"
    lines = [
        f"[bold]Model ID:[/bold]       {spec.model_id}",
        f"[bold]Name:[/bold]           {spec.name}",
        f"[bold]Parameters:[/bold]     {params}",
        f"[bold]Active Params:[/bold]  {active}",
        f"[bold]Context:[/bold]        {ctx_len}",
        f"[bold]Quantization:[/bold]   {spec.quantization.value}",
        f"[bold]Min VRAM:[/bold]       {vram}",
        f"[bold]Engines:[/bold]        {engines_str}",
        f"[bold]Provider:[/bold]       {provider}",
        f"[bold]API Key:[/bold]        {api_key}",
    ]

    # Append metadata fields with well-known labels
    meta_labels = {
        "architecture": "Architecture",
        "hf_repo": "HuggingFace",
        "url": "More Info",
        "teacher": "Teacher Model",
        "quantization": "Quant Format",
        "license": "License",
        "pricing_input": "Price (input)",
        "pricing_output": "Price (output)",
    }
    for key, label in meta_labels.items():
        value = spec.metadata.get(key)
        if value is not None:
            if key.startswith("pricing_"):
                value = f"${value}/M tokens"
            elif key == "hf_repo":
                value = f"https://huggingface.co/{value}"
            pad = " " * max(1, 14 - len(label))
            lines.append(f"[bold]{label}:[/bold]{pad}{value}")

    # Any remaining metadata not covered above
    extra_keys = set(spec.metadata) - set(meta_labels)
    for key in sorted(extra_keys):
        pad = " " * max(1, 14 - len(key))
        lines.append(f"[bold]{key}:[/bold]{pad}{spec.metadata[key]}")

    console.print(Panel("\n".join(lines), title=spec.name, border_style="blue"))


def ollama_pull(host: str, model_name: str, console: Console) -> bool:
    """Pull a model via Ollama API. Returns True on success.

    The pull stream can fail *after* the manifest step (disk full, network
    drop, registry rejecting the tag) by emitting an ``{"error": ...}``
    event instead of raising, so the stream is checked for error events
    and the result is verified against the server before success is
    reported — a silent failure here leaves the user with no model and a
    green message.
    """
    console.print(f"Pulling [cyan]{model_name}[/cyan] via Ollama...")
    try:
        with httpx.stream(
            "POST",
            f"{host}/api/pull",
            json={"name": model_name, "stream": True},
            timeout=600.0,
        ) as resp:
            resp.raise_for_status()
            import json

            for line in resp.iter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except Exception as exc:
                    soft_fail(logger, exc, "optional CLI step")
                    continue
                if "error" in data:
                    console.print(f"\n[red]Ollama error:[/red] {data['error']}")
                    return False
                status = data.get("status", "")
                if "total" in data and "completed" in data:
                    total = data["total"]
                    done = data["completed"]
                    pct = int(done / total * 100) if total else 0
                    console.print(f"  {status}: {pct}%", end="\r")
                elif status:
                    console.print(f"  {status}")
        # Verify the model actually exists server-side before claiming
        # success (catches truncated streams and name mismatches).
        with httpx.stream(
            "POST",
            f"{host}/api/show",
            json={"model": model_name},
            timeout=30.0,
        ) as verify:
            if verify.status_code != 200:
                console.print(
                    f"\n[red]Pull reported success but {model_name!r} is "
                    "not served by Ollama.[/red]\n"
                    f"Check the exact registry name with "
                    f"[cyan]ollama list[/cyan] and retry."
                )
                return False
        console.print(f"\n[green]Successfully pulled {model_name}[/green]")
        return True
    except httpx.ConnectError:
        console.print("[red]Cannot connect to Ollama.[/red] Is it running?")
        return False
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]Ollama error:[/red] {exc.response.status_code}")
        return False


def find_model_spec(model_name: str):
    """Look up a model in the builtin catalog. Returns None if not found."""
    for spec in BUILTIN_MODELS:
        if spec.model_id == model_name:
            return spec
    return None


def _gguf_runtime_ready(console: Console) -> bool:
    """Check llama-cpp-python is importable, with install guidance if not.

    Failing fast *before* a multi-GB download avoids the worst outcome:
    a fully downloaded model the engine cannot run.
    """
    try:
        import llama_cpp  # noqa: F401

        return True
    except ImportError:
        console.print(
            "[red]GGUF runtime not installed.[/red] The in-process GGUF "
            "engine needs llama-cpp-python:\n"
            "  [cyan]uv sync --extra inference-gguf[/cyan]  (or: "
            "[cyan]pip install llama-cpp-python --prefer-binary[/cyan])\n"
            "On Windows without a build chain, grab a prebuilt wheel from\n"
            "[cyan]https://github.com/abetlen/llama-cpp-python/releases[/cyan]."
        )
        return False


def gguf_pull(model_name: str, console: Console) -> bool:
    """Download a GGUF from Hugging Face into ``~/.nova_ai/models``.

    Accepts built-in GGUF catalog ids (``qwen2.5-0.5b``), intelligence-
    catalog model ids that carry ``hf_repo``/``gguf_file`` metadata
    (``qwen3.5:9b``), and any custom ``owner/repo::file.gguf`` pair from
    the Hub. Uses the resilient downloader so the file lands where the
    in-process GGUF engine discovers it — no huggingface-cli, no Ollama.
    """
    target = model_name
    if "::" not in model_name:
        engine_entry = next((m for m in GGUF_CATALOG if m["id"] == model_name), None)
        if engine_entry is not None:
            target = f"{engine_entry['repo_id']}::{engine_entry['filename']}"
        else:
            spec = find_model_spec(model_name)
            repo = spec.metadata.get("hf_repo", "") if spec else ""
            gguf = spec.metadata.get("gguf_file", "") if spec else ""
            if repo and gguf:
                target = f"{repo}::{gguf}"
    if "::" not in target:
        console.print(
            f"[red]No GGUF download info for {model_name}[/red]\n"
            "For any Hugging Face model use: [cyan]nova model pull "
            "owner/repo::model-file.gguf --engine gguf[/cyan]"
        )
        return False
    repo, _, filename = target.partition("::")
    console.print(f"Downloading [cyan]{filename}[/cyan] from {repo}...")

    def _progress(done: int, total: int) -> None:
        if total:
            console.print(
                f"  {done / 1_048_576:.0f} / {total / 1_048_576:.0f} MB", end="\r"
            )

    try:
        path = download_gguf_model(target, progress_callback=_progress)
    except Exception as exc:
        console.print(f"\n[red]Download failed:[/red] {exc}")
        return False
    console.print(f"\n[green]Saved to {path}[/green]")
    console.print("Run it locally (no Ollama needed):")
    console.print(f"  [cyan]nova chat --engine gguf --model {path.name}[/cyan]")
    return True


def hf_download(repo: str, filename: str | None, console: Console) -> bool:
    """Download from HuggingFace via huggingface-cli. Returns True on success."""
    cmd = ["huggingface-cli", "download", repo]
    if filename:
        cmd.append(filename)
    try:
        subprocess.run(cmd, check=True)
        console.print("[green]Download complete.[/green]")
        return True
    except FileNotFoundError:
        console.print(
            "[red]huggingface-cli not found.[/red]\n"
            "Install it: [cyan]pip install huggingface_hub[/cyan]\n"
            f"Or download manually: https://huggingface.co/{repo}"
        )
        return False
    except subprocess.CalledProcessError:
        console.print("[red]Download failed.[/red]")
        return False


@model.command()
@click.argument("model_name")
@click.option("--engine", default=None, help="Engine to download for.")
def pull(model_name: str, engine: str | None) -> None:
    """Download a model."""
    console = Console()
    config = load_config()
    engine = engine or config.engine.default or "ollama"

    if engine == "ollama":
        host = (
            config.engine.ollama_host
            or os.environ.get("OLLAMA_HOST")
            or "http://localhost:11434"
        ).rstrip("/")
        if not ollama_pull(host, model_name, console):
            sys.exit(1)
    elif engine in ("gguf", "llamacpp"):
        # Both routes download into ~/.nova_ai/models via the resilient
        # downloader: the in-process GGUF engine discovers loose files
        # there, and a llama.cpp server can serve the same files. The old
        # huggingface-cli route dropped files into the HF cache, which no
        # NOVA engine reads, leaving pulls unusable.
        if engine == "llamacpp":
            spec = find_model_spec(model_name)
            registry_tag = spec.metadata.get("ollama_registry_tag", "") if spec else ""
            has_gguf = bool(
                spec and spec.metadata.get("hf_repo") and spec.metadata.get("gguf_file")
            )
            # Catalog entries can name an Ollama registry tag directly (added
            # when the HF repo named by the catalog does not host a pullable
            # GGUF, e.g. granite4.0-*). Prefer the registry when present.
            if registry_tag and not has_gguf and "::" not in model_name:
                console.print(
                    f"[cyan]{model_name}[/cyan] is served by the Ollama "
                    f"registry as [cyan]{registry_tag}[/cyan]; pulling it."
                )
                ollama_host = (
                    config.engine.ollama_host
                    or os.environ.get("OLLAMA_HOST")
                    or "http://localhost:11434"
                ).rstrip("/")
                if not ollama_pull(ollama_host, registry_tag, console):
                    sys.exit(1)
                console.print(
                    f"[yellow]Note:[/yellow] pulled as {registry_tag!r} - "
                    f"pass that name when generating with this model."
                )
                return
        if not _gguf_runtime_ready(console):
            sys.exit(1)
        if not gguf_pull(model_name, console):
            sys.exit(1)
    elif engine == "mlx":
        spec = find_model_spec(model_name)
        if not spec:
            console.print(f"[red]Model not in catalog:[/red] {model_name}")
            sys.exit(1)
        mlx_repo = spec.metadata.get("mlx_repo", "")
        if not mlx_repo:
            console.print(f"[red]No MLX repo info for {model_name}[/red]")
            sys.exit(1)
        console.print(f"Downloading [cyan]{mlx_repo}[/cyan]...")
        if not hf_download(mlx_repo, None, console):
            sys.exit(1)
    elif engine in ("vllm", "sglang"):
        console.print(
            f"[cyan]{model_name}[/cyan] will download automatically when "
            f"{engine} starts serving it."
        )
    else:
        console.print(
            f"Manual download required for engine [cyan]{engine}[/cyan].\n"
            f"Check the engine documentation for instructions."
        )
