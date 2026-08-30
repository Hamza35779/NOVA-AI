"""CLI commands for Clipboard AI."""
from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel

from nova_ai.tools.clipboard_ai import (
    ClipboardAITool,
)

console = Console()


@click.group("clip")
def clip():
    """Clipboard AI — quickly summarize, translate, or explain clipboard content."""


@clip.command("summarize")
@click.option("--copy", is_flag=True, default=False, help="Copy result back to clipboard")
def clip_summarize(copy: bool):
    """Summarize text in clipboard."""
    tool = ClipboardAITool()
    res = tool.execute(action="summarize", copy_back=copy)
    console.print(Panel(res.content, title="[bold purple]NOVA AI Summary[/bold purple]", border_style="purple"))


@clip.command("explain")
@click.option("--copy", is_flag=True, default=False, help="Copy result back to clipboard")
def clip_explain(copy: bool):
    """Explain text/code in clipboard."""
    tool = ClipboardAITool()
    res = tool.execute(action="explain", copy_back=copy)
    console.print(Panel(res.content, title="[bold cyan]NOVA AI Explanation[/bold cyan]", border_style="cyan"))


@clip.command("translate")
@click.option("--lang", default="Spanish", help="Target language")
@click.option("--copy", is_flag=True, default=False, help="Copy result back to clipboard")
def clip_translate(lang: str, copy: bool):
    """Translate clipboard text."""
    tool = ClipboardAITool()
    res = tool.execute(action="translate", language=lang, copy_back=copy)
    console.print(Panel(res.content, title=f"[bold green]NOVA AI Translation ({lang})[/bold green]", border_style="green"))


@clip.command("fix")
@click.option("--copy", is_flag=True, default=False, help="Copy result back to clipboard")
def clip_fix(copy: bool):
    """Fix grammar and spelling in clipboard."""
    tool = ClipboardAITool()
    res = tool.execute(action="fix_grammar", copy_back=copy)
    console.print(Panel(res.content, title="[bold yellow]NOVA AI Grammar Fix[/bold yellow]", border_style="yellow"))
