"""Shared models, helpers, tool wiring, and MCP discovery for agent routes.

Split from ``agent_manager_routes.py`` (which was 2,494 lines with five
routers in one file). Everything here is import-safe without fastapi
installed except the pydantic request models (guarded like the original).
"""

from __future__ import annotations

import asyncio
import logging
import re as _re
import threading
from typing import Any, Dict, List, Optional, Tuple

from nova_ai.core.utils import soft_fail

try:
    from pydantic import BaseModel
except ImportError:  # pragma: no cover — server installs always have pydantic
    raise ImportError("fastapi and pydantic are required for server routes")

logger = logging.getLogger("nova_ai.server.agent_manager")

# Serializes first-request MCP discovery across concurrent requests; see
# _get_mcp_tools.
_mcp_discovery_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateAgentRequest(BaseModel):
    name: str
    agent_type: str = "monitor_operative"
    config: Optional[Dict[str, Any]] = None
    template_id: Optional[str] = None


class UpdateAgentRequest(BaseModel):
    name: Optional[str] = None
    agent_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class CreateTaskRequest(BaseModel):
    description: str


class UpdateTaskRequest(BaseModel):
    description: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[Dict[str, Any]] = None
    findings: Optional[List[Any]] = None


class BindChannelRequest(BaseModel):
    channel_type: str
    config: Optional[Dict[str, Any]] = None
    routing_mode: str = "dedicated"


class SendMessageRequest(BaseModel):
    content: str
    mode: str = "queued"
    stream: bool = False  # SSE streaming mode


class FeedbackRequest(BaseModel):
    score: float
    reason: Optional[str] = None


_BROWSER_SUB_TOOLS = {
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_screenshot",
    "browser_extract",
    "browser_axtree",
}


def _resolve_memory_backend(config: Any) -> Any:
    """Instantiate the configured memory backend, or None if unavailable.

    Mirrors serve.py's setup so an agent tick that runs through the server
    can actually use its memory_* tools. Returns None (so the tools degrade
    gracefully) when memory context is disabled or the backend can't load.
    """
    if config is None or not getattr(config.agent, "context_from_memory", False):
        return None
    try:
        import nova_ai.tools.storage  # noqa: F401
        from nova_ai.core.registry import MemoryRegistry

        key = config.memory.default_backend
        if MemoryRegistry.contains(key):
            return MemoryRegistry.create(key, db_path=config.memory.db_path)
    except Exception:
        logger.debug("Lightweight system: memory backend init failed", exc_info=True)
    return None


class _LightweightSystem:
    """Minimal system facade for the executor — avoids rebuilding the
    full NovaSystem (which picks a random model from Ollama)."""

    def __init__(self, engine: Any, model: str, config: Any = None):
        self.engine = engine
        self.model = model
        self.config = config
        # Wire the configured memory backend so an agent's memory_store /
        # memory_retrieve tools work when the tick runs through the server.
        # The executor injects system.memory_backend into those tools; this
        # facade previously left it None, so they reported "No memory backend
        # configured" even though the backend was configured and active.
        self.memory_backend = _resolve_memory_backend(config)


def _make_lightweight_system(
    engine: Any,
    model: str,
    config: Any = None,
) -> _LightweightSystem:
    """Build a minimal system with a fresh inference engine.

    The server's ``app.state.engine`` is heavily wrapped
    (MultiEngine -> InstrumentedEngine -> GuardrailsEngine) and can
    return empty content from background threads. Create a fresh
    engine directly (no health checks or model discovery that
    could interfere with in-flight requests).
    """
    try:
        from nova_ai.engine._discovery import get_engine

        cfg = config
        if cfg is None:
            from nova_ai.core.config import load_config

            cfg = load_config()

        pref = cfg.intelligence.preferred_engine
        key = pref or cfg.engine.default
        resolved = get_engine(cfg, key)

        if resolved is not None:
            plain_engine = resolved[1]
        else:
            from nova_ai.engine.ollama import OllamaEngine

            host = cfg.engine.ollama.host if cfg else ""
            plain_engine = OllamaEngine(host=host) if host else OllamaEngine()

        # Wrap with InstrumentedEngine so agent ticks are recorded
        # in telemetry (FLOPs, energy, cost savings).
        try:
            from nova_ai.core.events import get_event_bus
            from nova_ai.telemetry.instrumented_engine import (
                InstrumentedEngine,
            )

            plain_engine = InstrumentedEngine(
                plain_engine,
                get_event_bus(),
            )
        except Exception as exc:
            soft_fail(logger, exc, "telemetry is optional")
        return _LightweightSystem(plain_engine, model, cfg)
    except Exception as exc:
        soft_fail(logger, exc, "optional server subsystem")
    return _LightweightSystem(engine, model, config)


def _parse_param_count(model_name: str) -> float:
    """Extract parameter count in billions from model name.

    Examples: 'qwen3.5:9b' -> 9.0, 'qwen3.5:0.8b' -> 0.8
    """
    m = _re.search(r":(\d+(?:\.\d+)?)b", model_name.lower())
    return float(m.group(1)) if m else 0.0


_CLOUD_PREFIXES = ("gpt-", "claude-", "gemini-", "o1-", "o3-", "o4-")


def _pick_recommended_model(
    model_ids: list[str],
) -> dict[str, str]:
    """Pick the second-largest local model from a list."""
    local = [m for m in model_ids if not any(m.startswith(p) for p in _CLOUD_PREFIXES)]
    if not local:
        return {
            "model": model_ids[0] if model_ids else "",
            "reason": "Only model available",
        }
    sized = sorted(local, key=_parse_param_count, reverse=True)
    if len(sized) == 1:
        return {"model": sized[0], "reason": "Only local model available"}
    pick = sized[1]  # second-largest
    params = _parse_param_count(pick)
    return {
        "model": pick,
        "reason": f"Second-largest local model ({params}B parameters)",
    }


def _ensure_registries_populated() -> None:
    """Ensure ToolRegistry and ChannelRegistry are populated.

    If the registries are empty (e.g. cleared by test fixtures) but the
    modules are already cached in sys.modules, reload the individual
    submodules to re-execute their @register decorators.
    """
    import importlib
    import sys

    from nova_ai.core.registry import ChannelRegistry, ToolRegistry

    # First, try a normal import (works if modules haven't been imported yet)
    try:
        import nova_ai.channels  # noqa: F401
    except Exception as exc:
        soft_fail(logger, exc, "optional server subsystem")

    try:
        import nova_ai.tools  # noqa: F401
    except Exception as exc:
        soft_fail(logger, exc, "optional server subsystem")

    # Also try to import browser tools (not included in nova_ai.tools.__init__)
    for _browser_mod in ("nova_ai.tools.browser", "nova_ai.tools.browser_axtree"):
        try:
            importlib.import_module(_browser_mod)
        except Exception as exc:
            soft_fail(logger, exc, "optional server subsystem")

    # If registries are still empty, reload individual submodules from sys.modules
    if not ChannelRegistry.keys():
        for mod_name in list(sys.modules):
            if mod_name.startswith("nova_ai.channels.") and not mod_name.endswith(
                "_stubs"
            ):
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception as exc:
                    soft_fail(logger, exc, "optional server subsystem")

    if not ToolRegistry.keys():
        for mod_name in list(sys.modules):
            if (
                mod_name.startswith("nova_ai.tools.")
                and not mod_name.endswith("_stubs")
                and not mod_name.endswith("agent_tools")
            ):
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception as exc:
                    soft_fail(logger, exc, "optional server subsystem")

    # After reloading tools, also try browser tools if still not registered
    if not any(ToolRegistry.contains(n) for n in _BROWSER_SUB_TOOLS):
        for _browser_mod in (
            "nova_ai.tools.browser",
            "nova_ai.tools.browser_axtree",
        ):
            mod = sys.modules.get(_browser_mod)
            if mod is not None:
                try:
                    importlib.reload(mod)
                except Exception as exc:
                    soft_fail(logger, exc, "optional server subsystem")


def build_tools_list() -> List[Dict[str, Any]]:
    """Build unified tools list from ToolRegistry + ChannelRegistry."""
    import os

    from nova_ai.core.credentials import TOOL_CREDENTIALS
    from nova_ai.core.registry import ChannelRegistry, ToolRegistry

    _ensure_registries_populated()

    items: List[Dict[str, Any]] = []

    for name, tool_cls in ToolRegistry.items():
        if name in _BROWSER_SUB_TOOLS:
            continue
        # `spec` is an instance @property on BaseTool subclasses, so
        # we have to instantiate the tool to read it. The earlier
        # implementation used getattr(tool_cls, 'spec') which returns
        # the property descriptor and crashed on spec.description,
        # silently dropping every real tool from the picker.
        try:
            spec = tool_cls().spec
        except Exception as exc:
            logger.debug("Could not instantiate tool %s: %s", name, exc)
            spec = None
        cred_keys = TOOL_CREDENTIALS.get(name, [])
        items.append(
            {
                "name": name,
                "description": spec.description if spec else "",
                "category": spec.category if spec else "",
                "source": "tool",
                "requires_credentials": len(cred_keys) > 0,
                "credential_keys": cred_keys,
                "configured": (
                    all(bool(os.environ.get(k)) for k in cred_keys)
                    if cred_keys
                    else True
                ),
            }
        )

    try:
        if any(ToolRegistry.contains(n) for n in _BROWSER_SUB_TOOLS):
            items.append(
                {
                    "name": "browser",
                    "description": (
                        "Web browser automation"
                        " (navigate, click, type, screenshot, extract)"
                    ),
                    "category": "browser",
                    "source": "tool",
                    "requires_credentials": False,
                    "credential_keys": [],
                    "configured": True,
                }
            )
    except Exception as exc:
        soft_fail(logger, exc, "optional server subsystem")

    try:
        for name, _cls in ChannelRegistry.items():
            cred_keys = TOOL_CREDENTIALS.get(name, [])
            items.append(
                {
                    "name": name,
                    "description": (
                        f"{name.replace('_', ' ').title()} messaging channel"
                    ),
                    "category": "communication",
                    "source": "channel",
                    "requires_credentials": len(cred_keys) > 0,
                    "credential_keys": cred_keys,
                    "configured": (
                        all(bool(os.environ.get(k)) for k in cred_keys)
                        if cred_keys
                        else True
                    ),
                }
            )
    except Exception as exc:
        soft_fail(logger, exc, "optional server subsystem")

    return items


def _resolve_tool_specs(
    tool_config: Any,
) -> List[Dict[str, Any]]:
    """Convert a template's ``tools`` config into OpenAI-format function specs.

    The template TOML stores tools as a list of string names (e.g.
    ``["file_read", "shell_exec"]``). Engines expect OpenAI-shaped dicts:
    ``{"type": "function", "function": {"name, description, parameters"}}``.

    Special handling:
      * Dict entries pass through as-is (allows advanced configs to
        supply fully-formed specs).
      * ``browser`` is a synthetic display-only meta-tool that expands
        to the 6 real browser sub-tools (browser_navigate, click, …).
      * Channel names (``slack``, ``gmail``, …) come from the
        ``ChannelRegistry`` and are not directly callable by the LLM —
        they're destinations for ``channel_send``. Silently skip them.
      * Unknown tool names are dropped with a warning.
    """
    if not tool_config:
        return []

    from nova_ai.core.registry import ChannelRegistry, ToolRegistry

    _ensure_registries_populated()

    def _spec_dict_for(name: str) -> Optional[Dict[str, Any]]:
        try:
            spec = ToolRegistry.get(name)().spec
        except Exception as exc:
            logger.warning(
                "Could not build spec for tool '%s' (%s) — dropping",
                name,
                exc,
            )
            return None
        return {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }

    resolved: List[Dict[str, Any]] = []
    seen: set = set()

    for entry in tool_config:
        if isinstance(entry, dict):
            resolved.append(entry)
            continue
        if not isinstance(entry, str):
            continue

        # Expand the synthetic "browser" meta-tool into its sub-tools.
        if entry == "browser":
            for sub in _BROWSER_SUB_TOOLS:
                if sub in seen or not ToolRegistry.contains(sub):
                    continue
                spec_dict = _spec_dict_for(sub)
                if spec_dict:
                    resolved.append(spec_dict)
                    seen.add(sub)
            continue

        # Channels (slack, gmail, …) live in ChannelRegistry and aren't
        # callable by the LLM. Skip silently — the agent talks to them
        # through the `channel_send` tool with a `channel` argument.
        if ChannelRegistry.contains(entry):
            continue

        if not ToolRegistry.contains(entry):
            logger.warning(
                "Tool '%s' referenced in agent config but not in ToolRegistry",
                entry,
            )
            continue

        if entry in seen:
            continue
        spec_dict = _spec_dict_for(entry)
        if spec_dict:
            resolved.append(spec_dict)
            seen.add(entry)

    return resolved


# Per-agent sampler params forwarded to the engine when present in config.
# The OpenAI-compat engine passes **kwargs straight through to the upstream
# payload, so these reach local servers (vLLM / mlx_lm / etc.) that support
# them. Only forwarded when explicitly set, so default agents send nothing
# extra and engines that don't support a key never receive it. (#386)
_SAMPLER_PARAM_KEYS = (
    "top_p",
    "top_k",
    "min_p",
    "repetition_penalty",
    "frequency_penalty",
    "presence_penalty",
)


def _build_managed_system_prompt(system_prompt: str, app_config: Any) -> str:
    """Build the streaming managed-agent system prompt via SystemPromptBuilder.

    Routes the agent's own ``system_prompt`` through the same builder the
    CLI/ask path uses, so SOUL.md / MEMORY.md / USER.md persona files are
    injected for streaming chat too (#431). Returns the assembled prompt
    (caller decides whether to append a SYSTEM message); an agent with
    neither persona nor template yields an empty string, preserving the
    prior no-SYSTEM-message behavior.
    """
    from nova_ai.prompt.builder import SystemPromptBuilder

    builder = SystemPromptBuilder(
        agent_template=system_prompt or "",
        memory_files_config=getattr(app_config, "memory_files", None),
        system_prompt_config=getattr(app_config, "system_prompt", None),
    )
    return builder.build()


def _sampler_kwargs(config: Dict[str, Any]) -> Dict[str, Any]:
    """Extract per-agent sampler params from a managed agent's config (#386)."""
    out: Dict[str, Any] = {}
    for key in _SAMPLER_PARAM_KEYS:
        val = config.get(key)
        if val is not None:
            out[key] = val
    return out


def _replay_history_messages(
    history: List[Dict[str, Any]],
    exclude_id: str,
) -> List[Any]:
    """Rebuild prior-turn LLM messages from stored managed-agent history.

    When a stored assistant turn recorded ``tool_calls``, replay them as an
    assistant tool-use message followed by the corresponding tool-result
    messages — so the model sees its own prior tool pattern instead of
    regressing to fabricated tool output on later turns. Without this, only
    the assistant's text is replayed and the tool-use signal is lost (#382).
    """
    from nova_ai.core.types import Message, Role, ToolCall

    messages: List[Any] = []
    for m in reversed(history):
        if m.get("id") == exclude_id:
            continue
        direction = m.get("direction")
        if direction == "user_to_agent":
            messages.append(Message(role=Role.USER, content=m.get("content") or ""))
        elif direction == "agent_to_user":
            stored = m.get("tool_calls")
            if stored:
                calls = []
                results = []
                for i, tc in enumerate(stored):
                    call_id = f"hist-{m.get('id', '')}-{i}"
                    calls.append(
                        ToolCall(
                            id=call_id,
                            name=tc.get("tool", ""),
                            arguments=tc.get("arguments") or "",
                        )
                    )
                    results.append(
                        Message(
                            role=Role.TOOL,
                            content=str(tc.get("result", "")),
                            tool_call_id=call_id,
                            name=tc.get("tool", ""),
                        )
                    )
                messages.append(
                    Message(
                        role=Role.ASSISTANT,
                        content=m.get("content") or None,
                        tool_calls=calls,
                    )
                )
                messages.extend(results)
            else:
                messages.append(
                    Message(role=Role.ASSISTANT, content=m.get("content") or "")
                )
    return messages


async def _execute_local_tool(
    tool_name: str,
    tool_args: str,
    engine: Any,
    model: str,
    app_state: Any,
    bus: Any,
) -> Any:
    """Execute a local (non-MCP) tool off the event loop via asyncio.to_thread.

    Runs in a thread pool so slow tools (shell_exec, knowledge_search, …)
    don't block every other SSE stream and HTTP request. (#514)
    """
    from nova_ai.core.registry import ToolRegistry
    from nova_ai.tools._stubs import ToolCall as StubToolCall
    from nova_ai.tools._stubs import ToolExecutor

    tool_cls = ToolRegistry.get(tool_name)
    if tool_cls is None:
        raise ValueError(f"Tool {tool_name!r} not found in registry")

    tool_instance = _instantiate_managed_tool(
        tool_cls,
        tool_name,
        engine=engine,
        model=model,
        app_state=app_state,
    )
    # interactive=True + auto-approve callback: managed agents run unattended
    # (server-side), so there is no human to confirm with. The auto-approve
    # callback satisfies ToolExecutor's confirmation gate — including the
    # hard-required gate for shell_exec/code_interpreter, which now always
    # route through it (previously code_interpreter skipped confirmation
    # entirely because its spec lacked the flag). Operators who need those
    # tools blocked for managed agents should remove them from the agent's
    # tool list instead of relying on the confirmation layer.
    executor = ToolExecutor(
        tools=[tool_instance],
        bus=bus,
        interactive=True,
        confirm_callback=lambda _prompt: True,
    )
    return await asyncio.to_thread(
        executor.execute,
        StubToolCall(
            id="",
            name=tool_name,
            arguments=tool_args,
        ),
    )


def _instantiate_managed_tool(
    tool_cls: Any,
    name: str,
    *,
    engine: Any,
    model: str,
    app_state: Any,
) -> Any:
    """Instantiate a tool with the same dependency injection as the canonical
    ``cli/ask.py`` path, so ``memory_*`` / ``channel_*`` / ``llm`` tools work
    instead of silently failing with "No backend configured" (#395).
    """
    try:
        from nova_ai.cli.ask import (
            _CHANNEL_TOOLS,
            _MEMORY_TOOLS,
            _get_memory_backend,
        )
    except Exception:  # pragma: no cover - cli import should always succeed
        _MEMORY_TOOLS = frozenset()
        _CHANNEL_TOOLS = frozenset()
        _get_memory_backend = None

    if name in _MEMORY_TOOLS:
        backend = getattr(app_state, "memory_backend", None) if app_state else None
        if backend is None and app_state is not None and _get_memory_backend:
            cfg = getattr(app_state, "config", None)
            if cfg is not None:
                backend = _get_memory_backend(cfg)
        if backend is None:
            logger.warning(
                "Memory tool %r instantiated without a backend — calls will "
                "return no results.",
                name,
            )
        return tool_cls(backend=backend)
    if name in _CHANNEL_TOOLS:
        channel = getattr(app_state, "channel_bridge", None) if app_state else None
        if channel is None:
            logger.warning(
                "Channel tool %r instantiated without a channel — calls will "
                "fail with 'No channel backend configured'.",
                name,
            )
        return tool_cls(channel=channel)
    if name == "llm":
        return tool_cls(engine=engine, model=model)
    return tool_cls()


def _build_deep_research_tools(
    engine: Any,
    model: str,
    knowledge_db_path: str = "",
) -> list:
    """Build the 4 DeepResearch tools from a KnowledgeStore.

    Returns an empty list if the knowledge DB does not exist.
    """
    from pathlib import Path

    if not knowledge_db_path:
        from nova_ai.core.config import DEFAULT_CONFIG_DIR

        knowledge_db_path = str(DEFAULT_CONFIG_DIR / "knowledge.db")

    if not Path(knowledge_db_path).exists():
        return []

    from nova_ai.connectors.retriever import TwoStageRetriever
    from nova_ai.connectors.store import KnowledgeStore
    from nova_ai.tools.knowledge_search import KnowledgeSearchTool
    from nova_ai.tools.knowledge_sql import KnowledgeSQLTool
    from nova_ai.tools.scan_chunks import ScanChunksTool
    from nova_ai.tools.think import ThinkTool

    store = KnowledgeStore(knowledge_db_path)
    retriever = TwoStageRetriever(store)
    return [
        KnowledgeSearchTool(retriever=retriever),
        KnowledgeSQLTool(store=store),
        ScanChunksTool(store=store, engine=engine, model=model),
        ThinkTool(),
    ]


def _merge_tool_call_fragments(
    accumulated: Dict[int, Dict[str, Any]],
    fragments: List[Dict[str, Any]],
) -> None:
    """Merge incremental tool_call delta fragments into accumulated state.

    OpenAI-compatible APIs send tool_calls as incremental fragments keyed
    by ``index``. Each fragment may contain partial ``function.name`` and/or
    ``function.arguments`` strings that must be concatenated.
    """
    for frag in fragments:
        idx = frag.get("index", 0)
        if idx not in accumulated:
            accumulated[idx] = {
                "id": frag.get("id", ""),
                "type": "function",
                "function": {"name": "", "arguments": ""},
            }
        entry = accumulated[idx]
        if frag.get("id"):
            entry["id"] = frag["id"]
        fn = frag.get("function", {})
        if fn.get("name"):
            entry["function"]["name"] += fn["name"]
        if fn.get("arguments"):
            entry["function"]["arguments"] += fn["arguments"]


def _get_mcp_tools(app_state: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return (openai_tools_list, mcp_adapters_by_name).

    Lazily discovers MCP tools from config and caches them on ``app_state``
    so that subsequent requests reuse the same connections.

    Discovery involves subprocess/HTTP handshakes (seconds per server), so
    the whole body runs under a module-level lock — without it two
    concurrent first-requests both run the full discovery handshake for
    the same servers and double-append clients to ``_mcp_clients``.
    """
    cached = getattr(app_state, "_mcp_tools_cache", None)
    if cached is not None:
        return cached

    with _mcp_discovery_lock:
        # Double-check: another thread may have populated the cache while we
        # waited on the lock above.
        cached = getattr(app_state, "_mcp_tools_cache", None)
        if cached is not None:
            return cached
        return _discover_mcp_tools(app_state)


def _discover_mcp_tools(
    app_state: Any,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Run the actual MCP discovery (caller must hold _mcp_discovery_lock)."""
    import json as _json

    from nova_ai.core.config import load_config

    openai_tools: List[Dict[str, Any]] = []
    adapters_by_name: Dict[str, Any] = {}

    try:
        app_config = load_config()
    except Exception as exc:
        logger.warning("Failed to load config for MCP discovery: %s", exc)
        return openai_tools, adapters_by_name

    if not app_config.tools.mcp.enabled or not app_config.tools.mcp.servers:
        return openai_tools, adapters_by_name

    from nova_ai.mcp.client import MCPClient
    from nova_ai.mcp.transport import StdioTransport, StreamableHTTPTransport
    from nova_ai.tools.mcp_adapter import MCPToolProvider

    # Keep clients alive so transports persist for tool calls at runtime
    mcp_clients: list = getattr(app_state, "_mcp_clients", [])

    try:
        server_list = _json.loads(app_config.tools.mcp.servers)
    except (_json.JSONDecodeError, TypeError) as exc:
        logger.warning("Failed to parse MCP server config: %s", exc)
        return openai_tools, adapters_by_name

    if not isinstance(server_list, list):
        return openai_tools, adapters_by_name

    for server_cfg in server_list:
        cfg = _json.loads(server_cfg) if isinstance(server_cfg, str) else server_cfg
        name = cfg.get("name", "<unnamed>")
        url = cfg.get("url")
        # Bearer token from config — mirrors the builder.py fix for #461.
        token = cfg.get("token")
        command = cfg.get("command", "")
        args = cfg.get("args", [])

        try:
            if url:
                transport = StreamableHTTPTransport(url=url, token=token)
            elif command:
                transport = StdioTransport(command=[command] + args)
            else:
                logger.warning(
                    "MCP server '%s' has neither 'url' nor 'command' — skipping",
                    name,
                )
                continue

            client = MCPClient(transport)
            client.initialize()
            mcp_clients.append(client)

            provider = MCPToolProvider(client)
            discovered = provider.discover()

            # Per-server tool filtering
            include_tools = set(cfg.get("include_tools", []))
            exclude_tools = set(cfg.get("exclude_tools", []))
            if include_tools:
                discovered = [t for t in discovered if t.spec.name in include_tools]
            if exclude_tools:
                discovered = [t for t in discovered if t.spec.name not in exclude_tools]

            for adapter in discovered:
                spec = adapter.spec
                openai_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": spec.name,
                            "description": spec.description,
                            "parameters": spec.parameters,
                        },
                    }
                )
                adapters_by_name[spec.name] = adapter

            logger.info(
                "Discovered %d MCP tools from server '%s'",
                len(discovered),
                name,
            )
        except Exception as exc:
            logger.warning(
                "Failed to discover MCP tools from '%s': %s",
                name,
                exc,
            )

    app_state._mcp_clients = mcp_clients
    if openai_tools:
        app_state._mcp_tools_cache = (openai_tools, adapters_by_name)
    return openai_tools, adapters_by_name


def _sse_chunk(chunk_id: str, model: str, content: str) -> str:
    """Build a single SSE content chunk."""
    import json as _json

    data = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": None,
            }
        ],
    }
    return f"data: {_json.dumps(data)}\n\n"


def _tool_progress_label(tool_name: str, args: str) -> str:
    """Human-readable label for a tool call in progress."""
    labels = {
        "knowledge_search": "Searching your knowledge base",
        "knowledge_sql": "Querying data with SQL",
        "scan_chunks": "Scanning documents for semantic matches",
        "think": "Planning next step",
    }
    label = labels.get(tool_name, f"Using {tool_name}")
    if args and tool_name != "think":
        # Try to extract the query/question from args JSON
        try:
            import json as _json

            parsed = _json.loads(args)
            q = parsed.get("query") or parsed.get("question") or ""
            if q:
                label += f' — "{q[:50]}"'
        except Exception as exc:
            soft_fail(logger, exc, "optional server subsystem")
    return label


__all__ = [
    "BindChannelRequest",
    "CreateAgentRequest",
    "CreateTaskRequest",
    "FeedbackRequest",
    "SendMessageRequest",
    "UpdateAgentRequest",
    "UpdateTaskRequest",
    "_LightweightSystem",
    "_BROWSER_SUB_TOOLS",
    "_SAMPLER_PARAM_KEYS",
    "_build_deep_research_tools",
    "_build_managed_system_prompt",
    "_discover_mcp_tools",
    "_ensure_registries_populated",
    "_execute_local_tool",
    "_get_mcp_tools",
    "_instantiate_managed_tool",
    "_make_lightweight_system",
    "_merge_tool_call_fragments",
    "_pick_recommended_model",
    "_replay_history_messages",
    "_resolve_memory_backend",
    "_resolve_tool_specs",
    "_sampler_kwargs",
    "_sse_chunk",
    "_tool_progress_label",
    "build_tools_list",
]
