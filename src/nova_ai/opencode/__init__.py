"""opencode ↔ NOVA AI integration.

Two directions, both configured here:

1. **opencode uses NOVA AI models** — NOVA's OpenAI-compatible server
   (``nova serve`` → ``http://127.0.0.1:8000/v1``) is registered as an
   opencode custom provider, so local Ollama models behave like any other
   opencode model (``nova-ai/qwen3:8b``).
2. **opencode uses NOVA AI tools** — ``nova mcp serve`` (stdio) exposes the
   NOVA tool registry as an opencode local MCP server.

``nova opencode init`` writes both into ``opencode.json`` (merged, never
clobbering the user's own keys); ``nova opencode install`` fetches the
opencode CLI when it is missing.
"""

from nova_ai.opencode.config import (
    NOVA_PROVIDER_ID,
    build_config,
    current_default_model,
    detect_opencode,
    fetch_server_models,
    install_opencode,
    list_configured_models,
    merge_config,
    nova_command,
    persist_env_var,
    privacy_report,
    read_config,
    server_health,
    set_default_model,
    write_project_config,
)

__all__ = [
    "NOVA_PROVIDER_ID",
    "build_config",
    "current_default_model",
    "detect_opencode",
    "fetch_server_models",
    "install_opencode",
    "list_configured_models",
    "merge_config",
    "nova_command",
    "persist_env_var",
    "privacy_report",
    "read_config",
    "server_health",
    "set_default_model",
    "write_project_config",
]
