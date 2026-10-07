"""Tests for the excel_tool (.xlsx read/write via optional openpyxl)."""

from __future__ import annotations

import importlib
import json
import sys

import pytest

from nova_ai.tools.excel_tool import ExcelTool

openpyxl = pytest.importorskip("openpyxl")


@pytest.fixture()
def tool() -> ExcelTool:
    return ExcelTool()


class TestExcelToolSpec:
    def test_spec(self, tool: ExcelTool):
        assert tool.spec.name == "excel_tool"
        assert tool.spec.category == "productivity"
        assert tool.spec.requires_confirmation is False
        assert tool.spec.parameters["required"] == ["action", "path"]
        assert tool.spec.parameters["properties"]["action"]["enum"] == [
            "read",
            "write",
            "sheets",
        ]


class TestExcelWrite:
    def test_write_list_rows(self, tool: ExcelTool, tmp_path):
        target = tmp_path / "out.xlsx"
        result = tool.execute(
            action="write",
            path=str(target),
            rows=[[1, "a"], [2, "b"]],
        )
        assert result.success is True
        assert target.exists()
        assert result.metadata["row_count"] == 2
        assert result.metadata["column_count"] == 2

    def test_write_dict_rows_get_header_from_keys(
        self, tool: ExcelTool, tmp_path
    ):
        target = tmp_path / "out.xlsx"
        result = tool.execute(
            action="write",
            path=str(target),
            rows=[{"name": "Ada", "score": 95}, {"name": "Ben", "score": 88}],
        )
        assert result.success is True
        assert result.metadata["row_count"] == 3  # header + 2 data rows

    def test_write_with_explicit_headers(self, tool: ExcelTool, tmp_path):
        target = tmp_path / "out.xlsx"
        result = tool.execute(
            action="write",
            path=str(target),
            rows=[[1, 2]],
            headers=["x", "y"],
        )
        assert result.success is True
        assert result.metadata["row_count"] == 2

    def test_write_refuses_existing_file_without_overwrite(
        self, tool: ExcelTool, tmp_path
    ):
        target = tmp_path / "out.xlsx"
        target.write_bytes(b"original")
        result = tool.execute(action="write", path=str(target), rows=[[1]])
        assert result.success is False
        assert "already exists" in result.content
        assert target.read_bytes() == b"original"

    def test_write_overwrite_replaces_file(self, tool: ExcelTool, tmp_path):
        target = tmp_path / "out.xlsx"
        tool.execute(action="write", path=str(target), rows=[[1]])
        result = tool.execute(action="write", path=str(target), rows=[[9, 9]], overwrite=True)
        assert result.success is True
        check = tool.execute(action="read", path=str(target), header=False)
        assert check.metadata["rows"] == [[9, 9]]

    def test_write_rejects_empty_rows(self, tool: ExcelTool, tmp_path):
        result = tool.execute(action="write", path=str(tmp_path / "out.xlsx"), rows=[])
        assert result.success is False
        assert "non-empty" in result.content

    def test_write_rejects_mixed_dict_keys(self, tool: ExcelTool, tmp_path):
        result = tool.execute(
            action="write",
            path=str(tmp_path / "out.xlsx"),
            rows=[{"a": 1}, {"b": 2}],
        )
        assert result.success is False
        assert "different keys" in result.content

    def test_write_creates_parent_directories(self, tool: ExcelTool, tmp_path):
        target = tmp_path / "deep" / "nested" / "out.xlsx"
        result = tool.execute(action="write", path=str(target), rows=[[1]])
        assert result.success is True
        assert target.exists()


class TestExcelRead:
    def test_read_roundtrip_with_header(self, tool: ExcelTool, tmp_path):
        target = tmp_path / "data.xlsx"
        tool.execute(
            action="write",
            path=str(target),
            rows=[{"name": "Ada", "score": 95}, {"name": "Ben", "score": 88}],
        )
        result = tool.execute(action="read", path=str(target))
        assert result.success is True
        rows = result.metadata["rows"]
        assert rows == [
            {"name": "Ada", "score": 95},
            {"name": "Ben", "score": 88},
        ]
        assert result.metadata["headers"] == ["name", "score"]

    def test_read_without_header_returns_lists(self, tool: ExcelTool, tmp_path):
        target = tmp_path / "data.xlsx"
        tool.execute(action="write", path=str(target), rows=[["a", 1]])
        result = tool.execute(action="read", path=str(target), header=False)
        assert result.success is True
        assert result.metadata["rows"] == [["a", 1]]
        assert result.metadata["headers"] is None

    def test_read_max_rows_limits_output(self, tool: ExcelTool, tmp_path):
        target = tmp_path / "data.xlsx"
        tool.execute(
            action="write",
            path=str(target),
            rows=[[i] for i in range(10)],
            headers=["n"],
        )
        result = tool.execute(action="read", path=str(target), max_rows=3)
        assert result.success is True
        assert result.metadata["row_count"] == 3

    def test_read_dates_are_json_safe(self, tool: ExcelTool, tmp_path):
        import datetime as dt

        target = tmp_path / "dates.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["when", "value"])
        ws.append([dt.datetime(2026, 10, 7, 12, 30), 42])
        wb.save(target)

        result = tool.execute(action="read", path=str(target))
        assert result.success is True
        # Metadata must survive a JSON round-trip (trace/event serialization).
        json.dumps(result.metadata)
        assert result.metadata["rows"][0]["when"] == "2026-10-07T12:30:00"

    def test_read_by_sheet_index(self, tool: ExcelTool, tmp_path):
        target = tmp_path / "multi.xlsx"
        wb = openpyxl.Workbook()
        wb.active.title = "first"
        wb.active.append(["a"])
        wb.create_sheet("second").append(["b"])
        wb.save(target)

        result = tool.execute(action="read", path=str(target), sheet=2)
        assert result.success is True
        assert result.metadata["sheet"] == "second"

    def test_read_unknown_sheet_name(self, tool: ExcelTool, tmp_path):
        target = tmp_path / "one.xlsx"
        tool.execute(action="write", path=str(target), rows=[[1]])
        result = tool.execute(action="read", path=str(target), sheet="nope")
        assert result.success is False
        assert "not found" in result.content

    def test_read_missing_file(self, tool: ExcelTool, tmp_path):
        result = tool.execute(action="read", path=str(tmp_path / "gone.xlsx"))
        assert result.success is False
        assert "does not exist" in result.content


class TestExcelSheets:
    def test_sheets_lists_names_and_dimensions(self, tool: ExcelTool, tmp_path):
        target = tmp_path / "multi.xlsx"
        wb = openpyxl.Workbook()
        wb.active.title = "first"
        wb.active.append(["a", "b"])
        wb.create_sheet("second").append(["c"])
        wb.save(target)

        result = tool.execute(action="sheets", path=str(target))
        assert result.success is True
        names = [s["name"] for s in result.metadata["sheets"]]
        assert names == ["first", "second"]


class TestExcelErrors:
    def test_rejects_non_xlsx_path(self, tool: ExcelTool):
        result = tool.execute(action="read", path="sheet.xls")
        assert result.success is False
        assert ".xlsx" in result.content

    def test_rejects_empty_path(self, tool: ExcelTool):
        result = tool.execute(action="read", path="")
        assert result.success is False
        assert "no path" in result.content

    def test_unknown_action(self, tool: ExcelTool, tmp_path):
        result = tool.execute(action="pivot", path=str(tmp_path / "out.xlsx"))
        assert result.success is False
        assert "unknown action" in result.content

    def test_missing_openpyxl_fails_loudly_with_hint(
        self, tool: ExcelTool, tmp_path, monkeypatch: pytest.MonkeyPatch
    ):
        # Simulate the optional dependency being absent.
        for key in [k for k in sys.modules if k == "openpyxl" or k.startswith("openpyxl.")]:
            monkeypatch.delitem(sys.modules, key, raising=False)
        monkeypatch.setitem(sys.modules, "openpyxl", None)
        importlib.reload = importlib.reload  # keep importlib referenced
        result = tool.execute(action="write", path=str(tmp_path / "out.xlsx"), rows=[[1]])
        assert result.success is False
        assert "tools-excel" in result.content
        assert "uv pip install" in result.content
        assert result.metadata["missing_package"] == "openpyxl"
