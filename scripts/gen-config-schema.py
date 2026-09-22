#!/usr/bin/env python3
"""Regenerate configs/schema.json from the NovaConfig dataclass tree.

The JSON schema mirrors the *top-level sections* of ``~/.nova_ai/config.toml``
(one object per section, plus install provenance keys). The authoritative,
field-level schema is the dataclass tree itself in
``src/nova_ai/core/config/sections.py`` — this file exists so tooling outside
Python (editors, the repo validator in tests/test_config_schema.py) can see
which sections exist without importing the package.

Usage: python scripts/gen-config-schema.py [--check]
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "configs" / "schema.json"


def main(check: bool = False) -> int:
    from nova_ai.core.config.sections import NovaConfig

    fields = [
        f.name
        for f in dataclasses.fields(NovaConfig)
        if f.name not in ("hardware",)
    ]
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "NOVA AI config",
        "description": (
            "Top-level sections of ~/.nova_ai/config.toml, mirrored from the "
            "NovaConfig dataclass tree in src/nova_ai/core/config/sections.py. "
            "The authoritative schema is the dataclass itself: unknown keys are "
            "ignored at load time (see docs/getting-started/configuration.md), "
            "and `nova config set key value` validates keys against the same "
            "tree. Regenerate with: python scripts/gen-config-schema.py"
        ),
        "type": "object",
        "properties": {name: {"type": "object"} for name in fields},
        "additionalProperties": True,
    }
    content = json.dumps(schema, indent=2) + "\n"
    if check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != content:
            print("configs/schema.json is stale — run scripts/gen-config-schema.py")
            return 1
        return 0
    OUT.write_text(content, encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--check" in sys.argv))
