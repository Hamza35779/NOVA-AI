# Configs

`configs/nova_ai/config.toml` is the local-first default (Ollama / qwen).
Eval-specific examples (A100 / vLLM / cloud) live under `configs/examples/`.

Schema: `configs/schema.json` (validated by `tests/test_config_schema.py`).
Unknown TOML keys warn instead of silently dropping — see `core/config/loader.py`.

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
