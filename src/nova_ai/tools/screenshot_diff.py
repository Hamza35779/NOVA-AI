"""Screenshot Diff tool — visual regression loop for UI work.

Captures the screen (reusing :mod:`nova_ai.tools.screen_capture`) and
compares it pixel-wise against a stored baseline PNG. Reports the percentage
of changed pixels and the bounding box of the changed area, so an agent can
verify that a UI action produced the expected visual change — or catch an
unexpected one.

The diff core is pure Pillow and unit-testable without a display; only the
capture path needs ``mss``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.engine.self_optimizer import track_execution
from nova_ai.tools._stubs import BaseTool, ToolSpec
from nova_ai.tools.screen_capture import _capture_region

logger = logging.getLogger(__name__)


def _require_pillow() -> None:
    """Raise with an install hint when Pillow is unavailable."""
    try:
        from PIL import Image, ImageChops  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "Required dependency 'Pillow' is not installed. "
            "Install with: pip install Pillow"
        ) from exc


def diff_images(baseline: Any, current: Any) -> Dict[str, Any]:
    """Compare two PIL images pixel-wise.

    Returns a mapping with ``changed_percent`` (0–100), ``bbox`` (the
    ``(left, upper, right, lower)`` bounding box of changed pixels, or
    ``None`` when identical), and the ``diff`` image itself.
    """
    from PIL import ImageChops

    if baseline.size != current.size:
        raise ValueError(
            f"Image size mismatch: baseline is {baseline.width}x{baseline.height}, "
            f"current is {current.width}x{current.height}. Re-capture the baseline."
        )
    base = baseline.convert("RGB")
    now = current.convert("RGB")
    diff = ImageChops.difference(base, now)
    gray = diff.convert("L")
    # get_flattened_data() replaces the deprecated getdata() in Pillow 12+;
    # fall back for older Pillow (pyproject requires >= 10).
    flattened = getattr(gray, "get_flattened_data", None)
    pixels = list(flattened()) if callable(flattened) else list(gray.getdata())
    if not pixels:
        return {"changed_percent": 0.0, "bbox": None, "diff": diff}
    changed = sum(1 for value in pixels if value > 0)
    total_brightness = sum(pixels)
    changed_percent = total_brightness / (len(pixels) * 255) * 100.0
    void = changed == 0
    return {
        "changed_percent": changed_percent,
        "bbox": None if void else diff.getbbox(),
        "diff": diff,
    }


@ToolRegistry.register("screenshot_diff")
class ScreenshotDiffTool(BaseTool):
    """Capture baselines and diff the live screen against them."""

    tool_id = "screenshot_diff"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="screenshot_diff",
            description=(
                "Visual regression for UI work. Actions: 'baseline' captures the "
                "screen and stores it as the reference image; 'compare' captures "
                "again and reports how much changed versus the baseline "
                "(percentage of changed pixels plus the bounding box of the "
                "changed area). Use it to verify a UI action had the expected "
                "visual effect, or to detect unexpected popups and layout shifts."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["baseline", "compare"],
                        "description": "Capture a baseline, or compare against one.",
                    },
                    "baseline_path": {
                        "type": "string",
                        "description": (
                            "PNG file path for the baseline image. Written by "
                            "'baseline', read by 'compare'."
                        ),
                    },
                    "region": {
                        "type": "string",
                        "enum": ["full", "active_window"],
                        "description": "Screen region to capture.",
                        "default": "active_window",
                    },
                    "threshold": {
                        "type": "number",
                        "description": (
                            "Changed-pixel percentage above which the comparison "
                            "counts as DIFFER. Default 1.0."
                        ),
                        "default": 1.0,
                    },
                    "save_diff_path": {
                        "type": "string",
                        "description": (
                            "Optional path to save a highlight image of the "
                            "changed pixels (compare only)."
                        ),
                    },
                },
                "required": ["action", "baseline_path"],
            },
            category="perception",
            requires_confirmation=True,
            timeout_seconds=30.0,
        )

    @track_execution("screenshot_diff")
    def execute(
        self,
        action: str,
        baseline_path: str = "",
        region: str = "active_window",
        threshold: float = 1.0,
        save_diff_path: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        action = (action or "").lower().strip()
        if action not in ("baseline", "compare"):
            return ToolResult(
                tool_name="screenshot_diff",
                content="Error: unknown action "
                f"'{action}'. Use baseline or compare.",
                success=False,
            )
        if not baseline_path or not str(baseline_path).strip():
            return ToolResult(
                tool_name="screenshot_diff",
                content="Error: baseline_path is required.",
                success=False,
            )
        if region not in ("full", "active_window"):
            return ToolResult(
                tool_name="screenshot_diff",
                content=f"Error: unknown region '{region}'. Use full or active_window.",
                success=False,
            )
        try:
            threshold_value = float(threshold)
        except (TypeError, ValueError):
            return ToolResult(
                tool_name="screenshot_diff",
                content="Error: threshold must be a number.",
                success=False,
            )

        try:
            _require_pillow()
            from PIL import Image
        except RuntimeError as exc:
            return ToolResult(
                tool_name="screenshot_diff", content=f"Error: {exc}", success=False
            )

        target = Path(str(baseline_path).strip())
        try:
            current = _capture_region(region)
        except Exception as exc:  # noqa: BLE001 — capture backends vary by OS
            return ToolResult(
                tool_name="screenshot_diff",
                content=f"Error: screen capture failed: {exc}",
                success=False,
            )

        if action == "baseline":
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                current.save(str(target))
            except OSError as exc:
                return ToolResult(
                    tool_name="screenshot_diff",
                    content=f"Error: could not write baseline: {exc}",
                    success=False,
                )
            return ToolResult(
                tool_name="screenshot_diff",
                content=f"Saved baseline ({current.width}x{current.height}) to {target}.",
                success=True,
                metadata={
                    "action": "baseline",
                    "baseline_path": str(target),
                    "resolution": f"{current.width}x{current.height}",
                },
            )

        # Compare path.
        if not target.is_file():
            return ToolResult(
                tool_name="screenshot_diff",
                content=f"Error: baseline not found: {target}. Run 'baseline' first.",
                success=False,
            )
        try:
            baseline = Image.open(str(target))
            outcome = diff_images(baseline, current)
        except ValueError as exc:
            return ToolResult(
                tool_name="screenshot_diff",
                content=f"Error: {exc}",
                success=False,
            )
        except OSError as exc:
            return ToolResult(
                tool_name="screenshot_diff",
                content=f"Error: could not read baseline image: {exc}",
                success=False,
            )

        changed = outcome["changed_percent"]
        verdict = "DIFFER" if changed > threshold_value else "MATCH"
        content = (
            f"{verdict}: {changed:.2f}% of pixels changed "
            f"(threshold {threshold_value:.2f}%)."
        )
        if outcome["bbox"] is not None:
            left, upper, right, lower = outcome["bbox"]
            content += f" Changed area: ({left}, {upper})-({right}, {lower})."
        else:
            content += " Images are identical."

        metadata: Dict[str, Any] = {
            "action": "compare",
            "verdict": verdict,
            "changed_percent": changed,
            "bbox": list(outcome["bbox"]) if outcome["bbox"] is not None else None,
        }
        if save_diff_path and str(save_diff_path).strip():
            try:
                diff_path = Path(str(save_diff_path).strip())
                diff_path.parent.mkdir(parents=True, exist_ok=True)
                outcome["diff"].save(str(diff_path))
                metadata["diff_path"] = str(diff_path)
                content += f" Diff image saved to {diff_path}."
            except OSError as exc:
                content += f" Could not save diff image: {exc}."

        return ToolResult(
            tool_name="screenshot_diff",
            content=content,
            success=True,
            metadata=metadata,
        )


__all__ = ["ScreenshotDiffTool", "diff_images"]
