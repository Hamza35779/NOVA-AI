# Configs

`configs/nova_ai/config.toml` is the local-first default (Ollama / qwen).
Eval-specific examples (A100 / vLLM / cloud) live under `configs/examples/`.

Schema: `configs/schema.json` lists the valid top-level sections (mirrored from the
`NovaConfig` dataclass tree; regenerate with `python scripts/gen-config-schema.py`,
validated by `tests/test_config_schema.py`).

> **Known limitation:** the TOML loader (`core/config/loader.py`) silently ignores
> unknown sections/keys — a typo like `[intelligeence]` or `temprature` is dropped
> without a warning. `nova config set` *does* validate strictly (typos are rejected
> with the list of valid fields). Prefer `nova config set` for programmatic edits,
> and verify hand edits with `nova config show loaded`.

The eval-specific config for A100 / vLLM runs is `configs/nova_ai/config.toml`.
Per-preset starter configs referenced by `nova init --preset` live in `configs/nova_ai/examples/`
(smoke-tested by `tests/core/test_preset_configs.py`).

## Using a config

```bash
# Interactive setup — detects hardware and writes ~/.nova_ai/config.toml
nova init

# Point NOVA AI at a specific file (highest precedence)
export NOVA_AI_CONFIG=/path/to/config.toml
# …or copy a template straight to the user config location:
mkdir -p ~/.nova_ai && cp configs/nova_ai/config.toml ~/.nova_ai/config.toml
```

Precedence: `--config` flag → `NOVA_AI_CONFIG` env var → `~/.nova_ai/config.toml`.

## Inspecting and editing

```bash
nova config show           # print the loaded hierarchy
nova config set <k> <v>    # e.g. nova config set engine.default ollama
```
