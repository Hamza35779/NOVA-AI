"""FastAPI routes for the Agent Manager — compatibility facade.

The implementation was split (2,494 lines → package) into
``nova_ai/server/agent_manager/``:

- ``common``    — shared models, helpers, tool wiring, MCP discovery
- ``streaming`` — SSE streaming for managed-agent runs
- ``routers``   — the five APIRouters and ``create_agent_manager_router``

This module re-exports the full public + historically-imported private
surface so existing imports keep working unchanged:

- ``nova_ai.server.api_routes`` / ``tests`` import
  ``create_agent_manager_router`` from here.
- ``agents/executor.py`` imports ``_ensure_registries_populated``.
- ``channels/slack_daemon.py`` and ``server/webhook_routes.py`` import
  ``_build_deep_research_tools``.
- The streaming module re-imports ``_execute_local_tool`` by its former
  in-module name.
"""

from __future__ import annotations

from nova_ai.server.agent_manager.common import (  # noqa: F401
    BindChannelRequest,
    CreateAgentRequest,
    CreateTaskRequest,
    FeedbackRequest,
    SendMessageRequest,
    UpdateAgentRequest,
    UpdateTaskRequest,
    _build_deep_research_tools,
    _build_managed_system_prompt,
    _discover_mcp_tools,
    _ensure_registries_populated,
    _execute_local_tool,
    _get_mcp_tools,
    _instantiate_managed_tool,
    _LightweightSystem,
    _make_lightweight_system,
    _merge_tool_call_fragments,
    _parse_param_count,
    _pick_recommended_model,
    _replay_history_messages,
    _resolve_tool_specs,
    _sampler_kwargs,
    _sse_chunk,
    _tool_progress_label,
    build_tools_list,
)
from nova_ai.server.agent_manager.routers import (  # noqa: F401
    create_agent_manager_router,
)
from nova_ai.server.agent_manager.streaming import (  # noqa: F401
    _DEFAULT_LOCAL_MODEL,
    _DR_QUEUE_TIMEOUT_S,
    _stream_managed_agent,
)

__all__ = [
    "BindChannelRequest",
    "CreateAgentRequest",
    "CreateTaskRequest",
    "FeedbackRequest",
    "SendMessageRequest",
    "UpdateAgentRequest",
    "UpdateTaskRequest",
    "create_agent_manager_router",
    "build_tools_list",
]
