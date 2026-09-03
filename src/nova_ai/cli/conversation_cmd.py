"""``nova conversation`` — inspect and drive conversation trees from the CLI.

The desktop app owns the fork/race UI; the CLI is the headless fallback:
list conversations, render one as an ASCII tree, record sibling
choices as preference pairs, and count the preference data available
for the DPO lane.
"""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _db_path() -> Path:
    from nova_ai.core.paths import get_config_dir

    return get_config_dir() / "conversations.db"


def _store():
    from nova_ai.conversations.store import ConversationStore

    return ConversationStore(_db_path())


def _render_tree(nodes, children, node_id: str, prefix: str = "", is_last: bool = True, active_path=None) -> list[str]:
    """ASCII-render the subtree under *node_id* (depth-first, oldest first)."""
    lines = []
    node = next((n for n in nodes if n["id"] == node_id), None)
    if node is None:
        return lines
    connector = "" if prefix == "" else ("└─ " if is_last else "├─ ")
    role = node["role"]
    content = (node["content"] or "").replace("\n", " ")[:60]
    if role == "system":
        label = "(root)"
    else:
        model_part = f" {node['model']}" if node["model"] else ""
        label = f"[{role}]{model_part} {content}"
    marker = " ◀" if active_path and node_id in active_path else ""
    lines.append(f"{prefix}{connector}{label}{marker}")
    if prefix == "":
        child_prefix = ""
    else:
        child_prefix = prefix + ("   " if is_last else "│  ")
    kids = children.get(node_id, [])
    for i, child in enumerate(kids):
        lines.extend(
            _render_tree(
                nodes, children, child["id"], child_prefix, i == len(kids) - 1, active_path
            )
        )
    return lines


@click.group()
def conversation() -> None:
    """Conversation trees: forks, sibling answers, preference pairs."""


@conversation.command("list")
@click.option("-n", "--limit", default=20, type=int, help="Number of conversations.")
def list_cmd(limit: int) -> None:
    """List conversations (tree-shaped store)."""
    store = _store()
    convs = store.list_conversations(limit=limit)
    if not convs:
        console.print("No conversations yet. Forks from the app land here.")
        return
    table = Table(title="Conversations")
    table.add_column("ID", style="cyan")
    table.add_column("Title")
    table.add_column("Nodes", justify="right")
    table.add_column("Last activity", style="dim")
    for c in convs:
        table.add_row(c["id"], c["title"] or "—", str(c["node_count"]), (c["last_at"] or "")[:19])
    console.print(table)


@conversation.command()
@click.argument("conversation_id")
@click.option("--node", default="", help="Highlight the path to this node.")
def show(conversation_id: str, node: str) -> None:
    """Render a conversation as an ASCII tree."""
    store = _store()
    convs = {c["id"] for c in store.list_conversations(limit=10000)}
    if conversation_id not in convs:
        console.print(f"[red]Unknown conversation:[/red] {conversation_id}")
        raise SystemExit(1)
    with store._lock:  # noqa: SLF001
        rows = store._conn.execute(
            "SELECT id, conversation_id, parent_id, role, content, model, engine, "
            "created_at, metadata, feedback FROM conv_nodes "
            "WHERE conversation_id = ? ORDER BY created_at, id",
            (conversation_id,),
        ).fetchall()
    nodes = [store._row_to_node(r) for r in rows]
    children = {}
    for n in nodes:
        children.setdefault(n["parent_id"], []).append(n)
    roots = children.get(conversation_id, [])
    active_path = None
    if node:
        active_path = {m["id"] for m in store.path_to_root(node)}
    for root in roots:
        for line in _render_tree(nodes, children, root["id"], active_path=active_path):
            console.print(line)


@conversation.command()
@click.argument("node_id")
@click.option("--source", default="fork", type=click.Choice(["fork", "regen", "race", "thumbs"]))
def pick(node_id: str, source: str) -> None:
    """Record NODE_ID as the preferred sibling (writes a preference pair)."""
    store = _store()
    node = store.get_node(node_id)
    if node is None:
        console.print(f"[red]Unknown node:[/red] {node_id}")
        raise SystemExit(1)
    siblings = [
        c
        for c in store.children(node["parent_id"])
        if c["role"] == "assistant" and c["id"] != node_id
    ]
    if not siblings:
        console.print("[yellow]No sibling answers to prefer against.[/yellow]")
        raise SystemExit(1)
    prompt_path = store.path_to_root(node["parent_id"])
    pair_id = store.add_sibling_choice(
        node["conversation_id"],
        [m for m in prompt_path if m["role"] != "system"],
        node_id,
        [s["id"] for s in siblings],
        source=source,
    )
    console.print(f"[green]Preference pair recorded[/green] ({pair_id}): chose {node_id}")


@conversation.command("pairs")
@click.option("-n", "--limit", default=20, type=int)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def pairs_cmd(limit: int, as_json: bool) -> None:
    """Show recorded preference pairs (DPO training data)."""
    store = _store()
    pairs = store.list_preference_pairs(limit=limit)
    if as_json:
        console.print_json(json.dumps({"pairs": pairs, "total": len(pairs)}))
        return
    if not pairs:
        console.print(
            "No preference pairs yet. Fork/race in the app or use "
            "[bold]nova conversation pick[/bold]."
        )
        return
    table = Table(title=f"Preference Pairs ({store.count_preference_pairs()} total)")
    table.add_column("ID", style="cyan")
    table.add_column("Source")
    table.add_column("Chosen", style="green")
    table.add_column("Rejected", style="red")
    table.add_column("When", style="dim")
    for p in pairs:
        table.add_row(
            p["id"], p["source"], p["chosen_id"], ", ".join(p["rejected_ids"]), p["created_at"][:19]
        )
    console.print(table)


__all__ = ["conversation"]
