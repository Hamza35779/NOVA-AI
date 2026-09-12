#!/usr/bin/env python3
"""Soft god-file guard (P2): warn on files >800 lines (allowlist for legacy).

CI runs with --warn-only so legacy god-files don't block; new files over
budget fail when --strict is passed for changed files.
"""

from __future__ import annotations

import sys
from pathlib import Path

BUDGET = 800
ALLOWLIST = {
    "src/nova_ai/server/agent_manager_routes.py",
    "src/nova_ai/server/api_routes.py",
    "src/nova_ai/server/routes.py",
    "src/nova_ai/engine/cloud.py",
    "src/nova_ai/agents/hybrid/toolorchestra.py",
    "src/nova_ai/agents/hybrid/mini_swe_agent.py",
    "src/nova_ai/agents/hybrid/_base.py",
    "src/nova_ai/agents/hybrid/conductor.py",
    "src/nova_ai/agents/hybrid/runner.py",
    "src/nova_ai/agents/research_loop.py",
    "src/nova_ai/agents/manager.py",
    "src/nova_ai/agents/executor.py",
    "src/nova_ai/evals/cli.py",
    "src/nova_ai/evals/datasets/coding_assistant.py",
    "src/nova_ai/evals/datasets/doc_qa.py",
    "src/nova_ai/evals/datasets/security_scanner.py",
    "src/nova_ai/evals/core/runner.py",
    "src/nova_ai/evals/core/agentic_runner.py",
    "src/nova_ai/evals/environments/lifelong_agent_env.py",
    "src/nova_ai/evals/scorers/lifelong_agent_scorer.py",
    "src/nova_ai/core/config/sections.py",
    "src/nova_ai/cli/ask.py",
    "src/nova_ai/cli/mine_cmd.py",
    "src/nova_ai/cli/agent_cmd.py",
    "src/nova_ai/intelligence/model_catalog.py",
}

ROOT = Path(__file__).resolve().parent.parent


def main(strict: bool = False) -> int:
    offenders = []
    for p in list((ROOT / "src" / "nova_ai").rglob("*.py")):
        try:
            n = len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
        except OSError:
            continue
        if n > BUDGET and str(p.relative_to(ROOT)).replace("\\", "/") not in ALLOWLIST:
            offenders.append((str(p.relative_to(ROOT)), n))
    if offenders:
        print(f"{len(offenders)} files over {BUDGET} lines (non-allowlisted):")
        for path, n in sorted(offenders, key=lambda x: -x[1])[:20]:
            print(f"  {n:5d}  {path}")
        return 1 if strict else 0
    print(f"OK: no non-allowlisted files over {BUDGET} lines.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--strict" in sys.argv))
