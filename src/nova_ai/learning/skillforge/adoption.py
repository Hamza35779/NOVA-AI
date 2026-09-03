"""Skill adoption — install (and uninstall) forged skills.

``adopt_skill`` writes the manifest into
``~/.nova_ai/skills/generated/<name>/skill.toml`` with a provenance block
(``metadata.nova_ai.forge``: run id, pattern count, gauntlet report) and
adds the ``generated`` tag. ``discover_skills`` walks that layout
automatically (``skills/loader.py`` two-level walk), so an adopted skill
is live on the next skill discovery. ``revert_skill`` deletes the
directory — the only mutation reversal this feature needs.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from nova_ai.skills.types import SkillManifest

logger = logging.getLogger(__name__)

GENERATED_SUBDIR = "generated"


def generated_root(skills_root: Path) -> Path:
    return Path(skills_root) / GENERATED_SUBDIR


def _with_provenance(
    manifest: SkillManifest,
    *,
    run_id: str,
    gauntlet: dict[str, Any],
    pattern_count: int,
) -> SkillManifest:
    meta = dict(manifest.metadata or {})
    nova_meta = dict(meta.get("nova_ai", {}) or {})
    nova_meta["forge"] = {
        "run_id": run_id,
        "pattern_count": pattern_count,
        "gauntlet_passed": bool(gauntlet.get("passed")),
        "gates": gauntlet.get("gates", []),
    }
    meta["nova_ai"] = nova_meta
    tags = list(manifest.tags or [])
    if "generated" not in tags:
        tags.append("generated")
    return SkillManifest(
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        author=manifest.author,
        steps=manifest.steps,
        required_capabilities=manifest.required_capabilities,
        signature=manifest.signature,
        metadata=meta,
        tags=tags,
        depends=manifest.depends,
        user_invocable=manifest.user_invocable,
        disable_model_invocation=manifest.disable_model_invocation,
        markdown_content=manifest.markdown_content,
    )


def _manifest_to_toml(manifest: SkillManifest) -> str:
    """Serialize a manifest back into skill.toml form (stdlib tomli_w-free)."""
    import json as _json

    lines: list[str] = ["[skill]"]
    lines.append(f'name = "{manifest.name}"')
    lines.append(f'version = "{manifest.version}"')
    escaped_desc = manifest.description.replace('"', '\\"')
    lines.append(f'description = "{escaped_desc}"')
    lines.append(f'author = "{manifest.author}"')
    if manifest.required_capabilities:
        caps = ", ".join(f'"{c}"' for c in manifest.required_capabilities)
        lines.append(f"required_capabilities = [{caps}]")
    if manifest.tags:
        tags = ", ".join(f'"{t}"' for t in manifest.tags)
        lines.append(f"tags = [{tags}]")
    meta = (manifest.metadata or {}).get("nova_ai", {}).get("forge", {})
    if meta:
        lines.append("")
        lines.append("[skill.metadata.nova_ai.forge]")
        lines.append(f'run_id = "{meta.get("run_id", "")}"')
        lines.append(f'pattern_count = {int(meta.get("pattern_count", 0))}')
        lines.append(
            f'gauntlet_passed = {"true" if meta.get("gauntlet_passed") else "false"}'
        )
        # TOML basic string: JSON is embedded as text, so escape backslashes
        # and quotes (the JSON quotes themselves must not terminate ours).
        gates_json = _json.dumps(meta.get("gates", []))
        lines.append(f"gates = \"{gates_json.replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))}\"")
    for step in manifest.steps:
        lines.append("")
        lines.append("[[skill.steps]]")
        lines.append(f'tool_name = "{step.tool_name}"')
        if step.skill_name:
            lines.append(f'skill_name = "{step.skill_name}"')
        template = step.arguments_template.replace('"', '\\"').replace("\n", "\\n")
        lines.append(f'arguments_template = "{template}"')
        lines.append(f'output_key = "{step.output_key}"')
    return "\n".join(lines) + "\n"


def adopt_skill(
    manifest: SkillManifest,
    *,
    run_id: str,
    gauntlet: dict[str, Any],
    pattern_count: int,
    skills_root: Path,
) -> Path:
    """Write the skill into ``skills_root/generated/<name>/skill.toml``.

    Requires the gauntlet to have passed. Returns the written directory.
    """
    if not gauntlet.get("passed"):
        raise ValueError(
            "refusing to adopt a skill that has not passed the gauntlet"
        )
    stamped = _with_provenance(
        manifest, run_id=run_id, gauntlet=gauntlet, pattern_count=pattern_count
    )
    skill_dir = generated_root(skills_root) / manifest.name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "skill.toml").write_text(
        _manifest_to_toml(stamped), encoding="utf-8"
    )
    logger.info("Adopted forged skill %r (run %s)", manifest.name, run_id)
    return skill_dir


def revert_skill(name: str, *, skills_root: Path) -> bool:
    """Delete ``skills_root/generated/<name>``. True when removed."""
    skill_dir = generated_root(skills_root) / name
    if not skill_dir.exists():
        return False
    shutil.rmtree(skill_dir)
    logger.info("Reverted forged skill %r", name)
    return True


def load_adopted(name: str, *, skills_root: Path) -> Optional[Any]:
    """Load an adopted skill's manifest, or ``None`` when absent."""
    from nova_ai.skills.loader import load_skill

    path = generated_root(skills_root) / name / "skill.toml"
    if not path.exists():
        return None
    try:
        return load_skill(path)
    except Exception as exc:
        logger.warning("Adopted skill %r failed to load: %s", name, exc)
        return None


__all__ = ["adopt_skill", "generated_root", "load_adopted", "revert_skill"]
