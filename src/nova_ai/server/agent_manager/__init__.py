"""Agent manager route package (split from the former 2,500-line module).

Modules:
- ``common``       — shared models, helpers, tool wiring, MCP discovery
- ``streaming``    — SSE streaming for managed-agent runs
- ``agents_router`` — /v1/managed-agents + /v1/templates endpoints
- ``system_router`` — global agent health, recommended model, tools endpoints
- ``sendblue_router`` — SendBlue channel setup endpoints

``nova_ai.server.agent_manager_routes`` re-exports everything from here for
backward compatibility.
"""
