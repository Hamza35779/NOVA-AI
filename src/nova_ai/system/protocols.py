"""Structural protocols for substituting fakes in place of NovaSystem."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional, Protocol

if TYPE_CHECKING:
    from nova_ai.core.config import NovaConfig
    from nova_ai.core.events import EventBus
    from nova_ai.engine._stubs import InferenceEngine
    from nova_ai.security.capabilities import CapabilityPolicy
    from nova_ai.sessions.session import SessionStore
    from nova_ai.tools._stubs import BaseTool
    from nova_ai.tools.storage._stubs import MemoryBackend
    from nova_ai.traces.collector import TraceCollector
    from nova_ai.traces.store import TraceStore


class OrchestratorDeps(Protocol):
    """Minimum surface of NovaSystem that QueryOrchestrator depends on.

    Tests can satisfy this with a lightweight class — no need to construct
    the full NovaSystem dataclass or materialize every subsystem.
    """

    config: NovaConfig
    bus: EventBus
    engine: InferenceEngine
    engine_key: str
    model: str
    agent_name: str
    tools: List[BaseTool]
    memory_backend: Optional[MemoryBackend]
    capability_policy: Optional[CapabilityPolicy]
    session_store: Optional[SessionStore]
    trace_store: Optional[TraceStore]
    trace_collector: Optional[TraceCollector]  # written by _run_agent

    # Optional attribute (getattr with default) — declared for type clarity.
    _skill_few_shot_examples: Any
