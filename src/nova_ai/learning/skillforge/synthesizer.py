"""Turn a mined pattern into a real skill manifest via the local LLM.

``SkillSynthesizer`` prompts the model with the repeated tool sequence
(per-call arguments from real instances) plus the **catalog of tools that
actually exist** on this machine, and asks for a ``skill.toml`` body. The
output is validated the only way that matters: parse it with the stock
``skills.loader.load_skill`` — if it can't load, it isn't a skill.
"""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

from nova_ai.skills.types import SkillManifest

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?!-))*[a-z0-9]$|^[a-z0-9]$")

_SYNTHESIS_PROMPT = """\
You are a skill-synthesis engine for the NOVA AI assistant. The user has \
repeatedly performed the same multi-step tool workflow. Write a reusable \
skill that automates it, chaining ONLY the tools listed in the catalog.

Output ONLY a skill.toml file body (TOML, no markdown fences, no prose) \
in exactly this shape:

[skill]
name = "kebab-case-name"
version = "0.1.0"
description = "One sentence: what the skill does."
author = "nova-skillforge"
required_capabilities = []

[[skill.steps]]
tool_name = "tool_from_catalog"
arguments_template = '{{"param": "{{query}}"}}'
output_key = "step1_result"

Rules:
- Every step's tool_name MUST be a tool from the catalog. No invention.
- arguments_template is a JSON string with {{placeholder}} keys filled from \
the context (starts as {{query}}, plus each step's output_key).
- 2-5 steps. Reuse the observed call order. Keep argument values close to \
the real recorded calls.
- name must be lowercase kebab-case.

Tool catalog (name | description | parameters):
{catalog}

Repeated workflow (tool call order, with real arguments observed):
{workflow}

Worked examples:
{examples}
"""

_STEP_TABLE_HEADER = "| Step | Tool | Arguments (observed) |\n|---|---|---|\n"


def _tool_catalog() -> str:
    """Render the registered-tool catalog for the prompt."""
    from nova_ai.core.registry import ToolRegistry

    try:
        items = sorted(ToolRegistry.items())
        if not items:
            raise RuntimeError("registry empty")
    except Exception:
        # Registries are lazily populated; force the tool-module import.
        import nova_ai.tools  # noqa: F401

        items = sorted(ToolRegistry.items())

    lines: list[str] = []
    for name, tool in items:
        try:
            spec = tool.spec
            params = spec.parameters or {}
        except Exception:
            continue
        lines.append(f"- {name} | {spec.description} | params: {params}")
    return "\n".join(lines)


def _render_workflow(candidate: dict[str, Any]) -> str:
    seq = " -> ".join(candidate.get("sequence", []))
    lines = [f"Tool sequence (seen {candidate.get('count', '?')}x): {seq}"]
    lines.append(_STEP_TABLE_HEADER)
    example = (candidate.get("examples") or [{}])[0]
    for i, call in enumerate(example.get("calls", []), 1):
        args = str(call.get("arguments", {}))[:200]
        lines.append(f"| {i} | {call.get('tool', '?')} | {args} |")
    return "\n".join(lines)


def _render_examples(candidate: dict[str, Any]) -> str:
    blocks: list[str] = []
    for ex in candidate.get("examples", [])[:3]:
        blocks.append(f"Query: {ex.get('query', '')}")
        for call in ex.get("calls", []):
            blocks.append(f"  {call['tool']}({str(call.get('arguments', {}))[:160]})")
    return "\n".join(blocks) or "(none)"


class SkillSynthesizer:
    """Ask the local LLM to write a skill.toml for a repeated pattern."""

    def __init__(self, llm: Any, *, max_retries: int = 1) -> None:
        """
        Parameters
        ----------
        llm :
            Injection seam with ``generate(prompt) -> str``.
        max_retries :
            Parse failures get one retry with the loader's error attached.
        """
        self._llm = llm
        self._max_retries = max_retries

    def synthesize(
        self,
        candidate: dict[str, Any],
        *,
        suggested_name: Optional[str] = None,
    ) -> SkillManifest:
        """Return a parsed manifest; raises ``ValueError`` on failure."""
        prompt = _SYNTHESIS_PROMPT.format(
            catalog=_tool_catalog() or "(none registered)",
            workflow=_render_workflow(candidate),
            examples=_render_examples(candidate),
        )
        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                raw = self._llm.generate(prompt if attempt == 0 else _retry_prompt(prompt, last_error))
            except Exception as exc:
                raise ValueError(f"synthesis LLM failed: {exc}") from exc
            try:
                return _parse_skill_toml(raw, candidate=candidate)
            except ValueError as exc:
                last_error = exc
                logger.debug(
                    "Synthesis attempt %d failed to parse: %s", attempt + 1, exc
                )
        raise ValueError(f"skill synthesis failed after retries: {last_error}")


def _retry_prompt(original: str, error: Optional[Exception]) -> str:
    if error is None:
        return original
    return (
        f"{original}\n\nYour previous output could not be parsed: {error}\n"
        "Fix the TOML and output ONLY the corrected skill.toml body."
    )


def _parse_skill_toml(raw: str, *, candidate: dict[str, Any]) -> SkillManifest:
    """Extract, write, and stock-load a skill.toml body."""
    text = (raw or "").strip()
    if "```" in text:
        fence = re.search(r"```(?:toml)?\s*\n(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1).strip()

    manifest = _load_from_text(text)

    # Post-parse guards the loader can't know about.
    seq = candidate.get("sequence") or []
    tool_names = [s.tool_name or s.skill_name for s in manifest.steps]
    if not tool_names:
        raise ValueError("manifest has no steps")
    if seq and tool_names != seq:
        raise ValueError(
            f"step tools {tool_names} do not match observed sequence {list(seq)}"
        )
    return manifest


def _load_from_text(text: str) -> SkillManifest:
    from nova_ai.skills.loader import load_skill

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "skill.toml"
        path.write_text(text, encoding="utf-8")
        return load_skill(path)


def sanitize_name(name: str) -> str:
    """Coerce a proposed skill name into a valid kebab-case slug."""
    slug = (name or "").strip().lower()
    slug = re.sub(r"[^a-z0-9-]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        slug = "forged-skill"
    return slug[:64]


__all__ = ["SkillSynthesizer", "sanitize_name"]
