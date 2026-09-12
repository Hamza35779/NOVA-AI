# Configs

`configs/nova_ai/config.toml` is the local-first default (Ollama / qwen).
Eval-specific examples (A100 / vLLM / cloud) live under `configs/examples/`.

Schema: `configs/schema.json` (validated by `tests/test_config_schema.py`).
Unknown TOML keys warn instead of silently dropping — see `core/config/loader.py`.
