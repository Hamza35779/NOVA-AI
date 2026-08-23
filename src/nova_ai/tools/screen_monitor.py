from __future__ import annotations

import difflib
import time
from typing import Any

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.tools._stubs import BaseTool, ToolSpec
from nova_ai.tools.screen_capture import _capture_region, _extract_text


@ToolRegistry.register("screen_monitor")
class ScreenMonitorTool(BaseTool):
    tool_id = "screen_monitor"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="screen_monitor",
            description="Monitor screen periodically and notify on significant changes in OCR text.",
            parameters={
                "type": "object",
                "properties": {
                    "interval_seconds": {"type": "integer", "default": 5},
                    "duration_seconds": {"type": "integer", "default": 60},
                    "sensitivity": {
                        "type": "number",
                        "default": 0.1,
                        "description": "0-1, threshold of text ratio change.",
                    },
                },
            },
            category="perception",
            requires_confirmation=True,
            timeout_seconds=300.0,
        )

    def execute(
        self,
        interval_seconds: int = 5,
        duration_seconds: int = 60,
        sensitivity: float = 0.1,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            import mss  # noqa: F401
            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError:
            return ToolResult(
                tool_name="screen_monitor",
                content="Required dependency 'mss', 'Pillow', or 'pytesseract' is not installed.",
                success=False,
            )

        start_time = time.time()
        previous_text = ""
        changes_detected = []

        while time.time() - start_time < duration_seconds:
            try:
                img = _capture_region("active_window")
                current_text = _extract_text(img)

                if previous_text:
                    ratio = difflib.SequenceMatcher(
                        None, previous_text, current_text
                    ).ratio()
                    if ratio < (1.0 - sensitivity):
                        changes_detected.append(
                            {
                                "time": time.time(),
                                "ratio": ratio,
                                "previous_preview": previous_text[:100],
                                "current_preview": current_text[:100],
                            }
                        )

                previous_text = current_text
            except Exception as e:
                return ToolResult(
                    tool_name="screen_monitor",
                    content=str(e),
                    success=False,
                )

            time.sleep(interval_seconds)

        return ToolResult(
            tool_name="screen_monitor",
            content=f"Monitored screen for {time.time() - start_time:.1f}s. Detected {len(changes_detected)} changes.",
            success=True,
            metadata={
                "changes_detected": changes_detected,
                "total_monitored_seconds": time.time() - start_time,
            },
        )
