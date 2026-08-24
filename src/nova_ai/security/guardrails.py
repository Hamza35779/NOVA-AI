"""GuardrailsEngine — security-aware inference engine wrapper."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Tuple

from nova_ai.core.events import EventBus, EventType
from nova_ai.core.types import Message
from nova_ai.engine._stubs import InferenceEngine, StreamChunk
from nova_ai.security._stubs import BaseScanner
from nova_ai.security.scanner import PIIScanner, SecretScanner
from nova_ai.security.types import RedactionMode, ScanResult


class SecurityBlockError(Exception):
    """Raised when mode is BLOCK and security findings are detected."""


@lru_cache(maxsize=1)
def _default_redact_scanners() -> Tuple[List[BaseScanner], ...]:
    """Build the shared secret/PII scanner pair once per process."""
    return (SecretScanner(), PIIScanner())


def redact_messages(
    messages: Sequence[Message],
    *,
    scanners: Optional[List[BaseScanner]] = None,
) -> List[Message]:
    """Return copies of *messages* with secret/PII findings redacted.

    The mandatory pre-step for any transmission to a cloud provider
    (roadmap WS3 "redaction-before-cloud"): content that leaves the machine
    must never carry API keys, credentials, or personally identifying data,
    even when the caller forgot to run it through a ``GuardrailsEngine``.
    Originals are untouched — only the outbound copies are rewritten.
    """
    active_scanners: List[BaseScanner] = (
        list(scanners)
        if scanners is not None
        else list(_default_redact_scanners())
    )
    out: List[Message] = []
    for msg in messages:
        if not msg.content:
            out.append(msg)
            continue
        text = msg.content
        for scanner in active_scanners:
            text = scanner.redact(text)
        if text == msg.content:
            out.append(msg)
            continue
        out.append(
            Message(
                role=msg.role,
                content=text,
                name=msg.name,
                tool_calls=msg.tool_calls,
                tool_call_id=msg.tool_call_id,
                metadata=msg.metadata,
                images=msg.images,
            )
        )
    return out


class GuardrailsEngine(InferenceEngine):
    """Wraps an existing ``InferenceEngine`` with security scanning.

    Not registered in ``EngineRegistry`` — instantiated dynamically to wrap
    any engine at runtime.

    Parameters
    ----------
    engine:
        The wrapped inference engine.
    scanners:
        List of scanners to run.  Defaults to ``SecretScanner`` + ``PIIScanner``.
    mode:
        Action taken on findings: WARN, REDACT, or BLOCK.
    scan_input:
        Whether to scan input messages.
    scan_output:
        Whether to scan output content.
    bus:
        Optional event bus for publishing security events.
    """

    def __init__(
        self,
        engine: InferenceEngine,
        *,
        scanners: Optional[List[BaseScanner]] = None,
        mode: RedactionMode = RedactionMode.WARN,
        scan_input: bool = True,
        scan_output: bool = True,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._engine = engine
        self._scanners: List[BaseScanner] = (
            scanners
            if scanners is not None
            else [
                SecretScanner(),
                PIIScanner(),
            ]
        )
        self._mode = mode
        self._scan_input = scan_input
        self._scan_output = scan_output
        self._bus = bus

    # -- properties ----------------------------------------------------------

    @property
    def engine_id(self) -> str:  # type: ignore[override]
        """Delegate to the wrapped engine."""
        return self._engine.engine_id

    @property
    def is_cloud(self) -> bool:
        """Delegate — a guarded cloud engine must still classify as cloud
        (MultiEngine auto-routing and local-fallback checks read this)."""
        return bool(getattr(self._engine, "is_cloud", False))

    # -- scanning helpers ----------------------------------------------------

    def _scan_text(self, text: str) -> ScanResult:
        """Run all scanners on *text* and merge findings."""
        merged = ScanResult()
        for scanner in self._scanners:
            result = scanner.scan(text)
            merged.findings.extend(result.findings)
        return merged

    def _redact_text(self, text: str) -> str:
        """Run all scanners' redact() on *text*."""
        result = text
        for scanner in self._scanners:
            result = scanner.redact(result)
        return result

    def _handle_findings(
        self,
        text: str,
        result: ScanResult,
        direction: str,
    ) -> str:
        """Apply the configured mode to findings.

        Parameters
        ----------
        text:
            The original text.
        result:
            Scan result containing findings.
        direction:
            ``"input"`` or ``"output"`` — used in event data.

        Returns
        -------
        str
            Possibly modified text (unchanged for WARN, redacted for REDACT).

        Raises
        ------
        SecurityBlockError
            If mode is BLOCK.
        """
        finding_dicts = [
            {
                "pattern": f.pattern_name,
                "threat": f.threat_level.value,
                "description": f.description,
            }
            for f in result.findings
        ]

        if self._mode == RedactionMode.WARN:
            if self._bus:
                self._bus.publish(
                    EventType.SECURITY_ALERT,
                    {
                        "direction": direction,
                        "findings": finding_dicts,
                        "mode": "warn",
                    },
                )
            return text

        if self._mode == RedactionMode.REDACT:
            if self._bus:
                self._bus.publish(
                    EventType.SECURITY_ALERT,
                    {
                        "direction": direction,
                        "findings": finding_dicts,
                        "mode": "redact",
                    },
                )
            return self._redact_text(text)

        # BLOCK mode
        if self._bus:
            self._bus.publish(
                EventType.SECURITY_BLOCK,
                {
                    "direction": direction,
                    "findings": finding_dicts,
                    "mode": "block",
                },
            )
        raise SecurityBlockError(
            f"Security scan blocked {direction}: "
            f"{len(result.findings)} finding(s) detected"
        )

    # -- InferenceEngine interface -------------------------------------------

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Scan input, call wrapped engine, scan output."""
        # Scan input messages
        if self._scan_input:
            processed = list(messages)
            for i, msg in enumerate(processed):
                if msg.content:
                    result = self._scan_text(msg.content)
                    if not result.clean:
                        processed[i] = Message(
                            role=msg.role,
                            content=self._handle_findings(
                                msg.content,
                                result,
                                "input",
                            ),
                            name=msg.name,
                            tool_calls=msg.tool_calls,
                            tool_call_id=msg.tool_call_id,
                            metadata=msg.metadata,
                            images=msg.images,
                        )
            messages = processed

        # Call wrapped engine
        response = self._engine.generate(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        # Scan output
        if self._scan_output:
            content = response.get("content", "")
            if content:
                result = self._scan_text(content)
                if not result.clean:
                    response["content"] = self._handle_findings(
                        content, result, "output"
                    )

        return response

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Yield tokens in real-time, scan accumulated output post-hoc."""
        accumulated = []
        async for token in self._engine.stream(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            accumulated.append(token)
            yield token

        # Post-hoc scan of accumulated output for logging only
        if self._scan_output:
            full_output = "".join(accumulated)
            if full_output:
                result = self._scan_text(full_output)
                if not result.clean and self._bus:
                    finding_dicts = [
                        {
                            "pattern": f.pattern_name,
                            "threat": f.threat_level.value,
                            "description": f.description,
                        }
                        for f in result.findings
                    ]
                    self._bus.publish(
                        EventType.SECURITY_ALERT,
                        {
                            "direction": "output",
                            "findings": finding_dicts,
                            "mode": "stream_post_hoc",
                        },
                    )

    async def stream_full(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator["StreamChunk"]:
        """Delegate to wrapped engine, scan accumulated output post-hoc."""
        accumulated: list[str] = []
        async for chunk in self._engine.stream_full(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            if chunk.content:
                accumulated.append(chunk.content)
            yield chunk

        # Post-hoc scan of accumulated output
        if self._scan_output:
            full_output = "".join(accumulated)
            if full_output:
                result = self._scan_text(full_output)
                if not result.clean and self._bus:
                    finding_dicts = [
                        {
                            "pattern": f.pattern_name,
                            "threat": f.threat_level.value,
                            "description": f.description,
                        }
                        for f in result.findings
                    ]
                    self._bus.publish(
                        EventType.SECURITY_ALERT,
                        {
                            "direction": "output",
                            "findings": finding_dicts,
                            "mode": "stream_full_post_hoc",
                        },
                    )

    def list_models(self) -> List[str]:
        """Delegate to wrapped engine."""
        return self._engine.list_models()

    def health(self) -> bool:
        """Delegate to wrapped engine."""
        return self._engine.health()


__all__ = ["GuardrailsEngine", "SecurityBlockError", "redact_messages"]
