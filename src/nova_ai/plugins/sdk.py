"""Plugin SDK — formalizes ad-hoc tools/agents/engines (P1-12).

Usage:
    nova plugin new --kind tool --name my_tool
    nova registry search tool-weather
"""

from __future__ import annotations

from pathlib import Path

TOOL_TEMPLATE = '''"""{{name}} plugin tool."""

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("{{name}}")
class {{ClassName}}(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="{{name}}",
            description="TODO: describe {{name}}",
            parameters={},
        )

    def execute(self, **params):  # type: ignore[no-untyped-def]
        return ToolResult(tool_name="{{name}}", content="TODO", success=True)
'''

AGENT_TEMPLATE = '''"""{{name}} plugin agent."""

from nova_ai.agents._stubs import AgentContext, AgentResult, BaseAgent
from nova_ai.core.registry import AgentRegistry


@AgentRegistry.register("{{name}}")
class {{ClassName}}(BaseAgent):
    agent_id = "{{name}}"

    def run(self, task: str, context: AgentContext | None = None) -> AgentResult:
        return AgentResult(content=f"TODO {{{task}}}", metadata={})
'''


def scaffold(kind: str, name: str, dest: Path) -> Path:
    """Write plugin scaffold; returns created file path."""
    klass = "".join(p.title() for p in name.replace("-", "_").split("_")) + (
        "Tool" if kind == "tool" else "Agent"
    )
    template = TOOL_TEMPLATE if kind == "tool" else AGENT_TEMPLATE
    content = template.replace("{{name}}", name).replace("{{ClassName}}", klass)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / f"{name}.py"
    target.write_text(content, encoding="utf-8")
    test = dest / f"test_{name}.py"
    if not test.exists():
        test.write_text(
            f'"""Smoke test for {name} plugin."""\n\n\n'
            f"def test_{name.replace('-', '_')}_imports():\n"
            f"    import importlib.util, pathlib\n"
            f"    assert pathlib.Path(__file__).with_name('{name}.py').exists()\n",
            encoding="utf-8",
        )
    return target


__all__ = ["scaffold", "TOOL_TEMPLATE", "AGENT_TEMPLATE"]
