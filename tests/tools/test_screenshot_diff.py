"""Tests for the screenshot_diff tool.

The diff core is exercised with synthetic Pillow images (no display needed).
Capture is monkeypatched at the tool boundary.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from nova_ai.tools.screenshot_diff import ScreenshotDiffTool, diff_images

pytest.importorskip("PIL.Image")

from PIL import Image  # noqa: E402


def _solid(color: tuple[int, int, int], size: tuple[int, int] = (20, 20)) -> Any:
    return Image.new("RGB", size, color)


@pytest.fixture()
def tool() -> ScreenshotDiffTool:
    return ScreenshotDiffTool()


class TestDiffImages:
    def test_identical_images_match(self):
        outcome = diff_images(_solid((10, 20, 30)), _solid((10, 20, 30)))
        assert outcome["changed_percent"] == 0.0
        assert outcome["bbox"] is None

    def test_fully_changed_image(self):
        outcome = diff_images(_solid((0, 0, 0)), _solid((255, 255, 255)))
        assert outcome["changed_percent"] == pytest.approx(100.0)
        assert outcome["bbox"] == (0, 0, 20, 20)

    def test_partial_change_bbox(self):
        base = _solid((0, 0, 0))
        changed = base.copy()
        changed.paste(Image.new("RGB", (5, 5), (255, 255, 255)), (2, 3))
        outcome = diff_images(base, changed)
        assert 0.0 < outcome["changed_percent"] < 100.0
        assert outcome["bbox"] == (2, 3, 7, 8)

    def test_size_mismatch_rejected(self):
        with pytest.raises(ValueError, match="size mismatch"):
            diff_images(_solid((0, 0, 0)), _solid((0, 0, 0), (10, 10)))


class TestScreenshotDiffToolSpec:
    def test_spec(self, tool: ScreenshotDiffTool):
        assert tool.spec.name == "screenshot_diff"
        assert tool.spec.category == "perception"
        assert tool.spec.requires_confirmation is True
        assert set(tool.spec.parameters["required"]) == {"action", "baseline_path"}


class TestScreenshotDiffTool:
    def test_unknown_action(self, tool: ScreenshotDiffTool, tmp_path):
        result = tool.execute(
            action="rotate", baseline_path=str(tmp_path / "base.png")
        )
        assert result.success is False
        assert "unknown action" in result.content

    def test_missing_baseline_path(self, tool: ScreenshotDiffTool):
        result = tool.execute(action="compare", baseline_path="")
        assert result.success is False
        assert "baseline_path is required" in result.content

    def test_bad_region(self, tool: ScreenshotDiffTool, tmp_path):
        result = tool.execute(
            action="compare",
            baseline_path=str(tmp_path / "base.png"),
            region="left_monitor",
        )
        assert result.success is False
        assert "unknown region" in result.content

    def _patch_capture(self, image: Any):
        return patch(
            "nova_ai.tools.screenshot_diff._capture_region", return_value=image
        )

    def test_baseline_then_compare_match(self, tool: ScreenshotDiffTool, tmp_path):
        base_path = str(tmp_path / "base.png")
        shot = _solid((1, 2, 3))
        with self._patch_capture(shot):
            saved = tool.execute(action="baseline", baseline_path=base_path)
        assert saved.success is True

        with self._patch_capture(_solid((1, 2, 3))):
            result = tool.execute(action="compare", baseline_path=base_path)
        assert result.success is True
        assert result.metadata["verdict"] == "MATCH"
        assert result.metadata["changed_percent"] == 0.0

    def test_compare_detects_change(self, tool: ScreenshotDiffTool, tmp_path):
        base_path = tmp_path / "base.png"
        _solid((0, 0, 0)).save(str(base_path))
        with self._patch_capture(_solid((255, 255, 255))):
            result = tool.execute(
                action="compare", baseline_path=str(base_path), threshold=0.5
            )
        assert result.success is True
        assert result.metadata["verdict"] == "DIFFER"
        assert result.metadata["changed_percent"] == pytest.approx(100.0)
        assert result.metadata["bbox"] == [0, 0, 20, 20]

    def test_compare_below_threshold_matches(
        self, tool: ScreenshotDiffTool, tmp_path
    ):
        base_path = tmp_path / "base.png"
        _solid((0, 0, 0)).save(str(base_path))
        with self._patch_capture(_solid((255, 255, 255))):
            result = tool.execute(
                action="compare", baseline_path=str(base_path), threshold=100.0
            )
        assert result.success is True
        assert result.metadata["verdict"] == "MATCH"

    def test_compare_missing_baseline(self, tool: ScreenshotDiffTool, tmp_path):
        with self._patch_capture(_solid((0, 0, 0))):
            result = tool.execute(
                action="compare",
                baseline_path=str(tmp_path / "never-captured.png"),
            )
        assert result.success is False
        assert "baseline not found" in result.content

    def test_compare_size_mismatch(self, tool: ScreenshotDiffTool, tmp_path):
        base_path = tmp_path / "base.png"
        _solid((0, 0, 0), (10, 10)).save(str(base_path))
        with self._patch_capture(_solid((0, 0, 0), (20, 20))):
            result = tool.execute(action="compare", baseline_path=str(base_path))
        assert result.success is False
        assert "size mismatch" in result.content

    def test_compare_saves_diff_image(self, tool: ScreenshotDiffTool, tmp_path):
        base_path = tmp_path / "base.png"
        _solid((0, 0, 0)).save(str(base_path))
        diff_path = str(tmp_path / "diff.png")
        with self._patch_capture(_solid((255, 0, 0))):
            result = tool.execute(
                action="compare",
                baseline_path=str(base_path),
                save_diff_path=diff_path,
            )
        assert result.success is True
        assert result.metadata["diff_path"] == diff_path
        assert (tmp_path / "diff.png").is_file()
