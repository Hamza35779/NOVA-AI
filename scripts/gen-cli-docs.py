#!/usr/bin/env python3
"""Regenerate docs/cli/ from `nova --help` (P1-6 / PR-8).

Kills CLI-doc rot: README links here instead of hand-maintaining 60+ commands.
Usage: python scripts/gen-cli-docs.py [--check]  (--check fails if stale, for CI)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "cli"


def _run(*args: str) -> str:
    return subprocess.run(list(args), capture_output=True, text=True, check=True).stdout


def main(check: bool = False) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        top = _run(sys.executable, "-m", "nova_ai.cli", "--help")
    except Exception:
        try:
            top = _run("nova", "--help")
        except Exception as exc:
            print(f"cannot invoke nova CLI: {exc}")
            return 1
    target = OUT / "index.md"
    content = "# CLI Reference (auto-generated)\n\n```text\n" + top + "\n```\n"
    if check:
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            print("docs/cli/index.md is stale — run scripts/gen-cli-docs.py")
            return 1
        return 0
    target.write_text(content, encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--check" in sys.argv))
