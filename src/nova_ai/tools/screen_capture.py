"""Screen capture tool — grabs the full screen or the active window and optionally OCRs it."""

from __future__ import annotations

import datetime
import shutil
import subprocess
import sys
from typing import Any, Optional

from nova_ai.core.registry import ToolRegistry
from nova_ai.core.types import ToolResult
from nova_ai.tools._stubs import BaseTool, ToolSpec


def _get_active_window_rect() -> Optional[tuple[int, int, int, int]]:
    """Get (left, top, width, height) of the active window.

    Supports Windows via the Win32 API and Linux via xdotool/wmctrl.
    Returns None when unsupported or on failure (caller falls back to full screen).
    """
    if sys.platform == "win32":
        try:
            # Lazy import: ctypes/wintypes are only needed on Windows.
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.pointer(rect))
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width <= 0 or height <= 0:
                return None
            return (rect.left, rect.top, width, height)
        except Exception:
            return None

    if sys.platform.startswith("linux"):
        # Preferred: xdotool reports geometry of the currently focused window.
        if shutil.which("xdotool"):
            try:
                out = subprocess.run(
                    ["xdotool", "getactivewindow", "getwindowgeometry", "--shell"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                fields = dict(
                    line.split("=", 1)
                    for line in out.stdout.strip().splitlines()
                    if "=" in line
                )
                left, top = int(fields["X"]), int(fields["Y"])
                width, height = int(fields["WIDTH"]), int(fields["HEIGHT"])
                if width > 0 and height > 0:
                    return (left, top, width, height)
            except Exception:
                pass
        # Fallback: wmctrl -lG lists windows; first line with active desktop hint is approximate.
        if shutil.which("wmctrl"):
            try:
                out = subprocess.run(
                    ["wmctrl", "-lG"], capture_output=True, text=True, timeout=5
                )
                for line in out.stdout.strip().splitlines():
                    parts = line.split()
                    # columns: desktop, winid, x, y, w, h, host
                    if len(parts) >= 7 and parts[0] != "-1":
                        left, top, width, height = (
                            int(parts[2]),
                            int(parts[3]),
                            int(parts[4]),
                            int(parts[5]),
                        )
                        if width > 0 and height > 0:
                            return (left, top, width, height)
            except Exception:
                pass
        return None

    # macOS / other platforms: no reliable active-window source without extra deps.
    return None


def _capture_region(region_name: str) -> Any:
    """Capture a screen region returning a PIL Image."""
    import mss
    from PIL import Image

    def _grab(sct: Any, monitor: dict) -> Any:
        sct_img = sct.grab(monitor)
        return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

    with mss.mss() as sct:
        if region_name == "full":
            return _grab(sct, sct.monitors[1])

        if region_name == "active_window":
            rect = _get_active_window_rect()
            if rect is not None:
                left, top, width, height = rect
                return _grab(
                    sct, {"top": top, "left": left, "width": width, "height": height}
                )
            # Active window unavailable (unsupported platform / headless): fall back to full screen.
            return _grab(sct, sct.monitors[1])

        raise ValueError(
            f"Unknown region '{region_name}'. Use 'full' or 'active_window'."
        )


def _extract_text(image: Any) -> str:
    """Extract text from a PIL Image using pytesseract."""
    import pytesseract

    return pytesseract.image_to_string(image)


@ToolRegistry.register("screen_capture")
class ScreenCaptureTool(BaseTool):
    """Captures the screen or active window, persists an optional PNG, and extracts text via OCR."""

    tool_id = "screen_capture"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="screen_capture",
            description="Capture the current screen or active window, extract text via OCR, and return the content. Useful for understanding what the user is looking at.",
            parameters={
                "type": "object",
                "properties": {
                    "region": {
                        "type": "string",
                        "enum": ["full", "active_window"],
                        "default": "active_window",
                    },
                    "extract_text": {"type": "boolean", "default": True},
                    "save_path": {
                        "type": "string",
                        "description": "Optional file path (.png/.jpg) to persist the captured screenshot.",
                    },
                },
            },
            category="perception",
            requires_confirmation=True,
            timeout_seconds=15.0,
        )

    def execute(
        self,
        region: str = "active_window",
        extract_text: bool = True,
        save_path: Optional[str] = None,
        **kwargs: Any,
    ) -> ToolResult:
        try:
            import mss  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError:
            return ToolResult(
                tool_name="screen_capture",
                content="Required dependency 'mss' or 'Pillow' is not installed. Install with: pip install mss Pillow",
                success=False,
            )

        try:
            image = _capture_region(region)

            metadata: dict[str, Any] = {
                "resolution": f"{image.width}x{image.height}",
                "timestamp": datetime.datetime.now().isoformat(),
                "region_requested": region,
            }

            if save_path:
                try:
                    image.save(save_path)
                    metadata["saved_path"] = str(save_path)
                except OSError as exc:
                    metadata["save_error"] = (
                        f"Could not save screenshot to '{save_path}': {exc}"
                    )

            text_content = ""
            if extract_text:
                try:
                    text_content = _extract_text(image)
                except ImportError:
                    text_content = "[OCR unavailable: pytesseract is not installed. Install with: pip install pytesseract]"
                except Exception as e:
                    text_content = f"[OCR error: {e}]"

            if save_path and "saved_path" in metadata:
                saved_note = f" Screenshot saved to {metadata['saved_path']}."
                text_content = (
                    f"{text_content}{saved_note}"
                    if text_content
                    else f"Screenshot saved to {metadata['saved_path']}."
                )

            return ToolResult(
                tool_name="screen_capture",
                content=text_content,
                success=True,
                metadata=metadata,
            )
        except Exception as e:
            return ToolResult(
                tool_name="screen_capture",
                content=f"Screen capture failed: {e}",
                success=False,
            )
