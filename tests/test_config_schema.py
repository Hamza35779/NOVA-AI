"""Validate configs/ against configs/schema.json (P1-4)."""

import json
from pathlib import Path

import pytest

try:
    import jsonschema  # type: ignore[import-not-found]

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


def test_schema_file_exists():
    assert (Path(__file__).parent.parent / "configs" / "schema.json").exists()


@pytest.mark.skipif(not HAS_JSONSCHEMA, reason="jsonschema not installed")
def test_example_configs_validate():
    import tomllib

    root = Path(__file__).parent.parent
    schema = json.loads((root / "configs" / "schema.json").read_text())
    for toml_path in list((root / "configs").rglob("*.toml"))[:20]:
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        jsonschema.validate(data, schema)
