"""Tests for the notebook_generator tool."""

from __future__ import annotations

import json

from nova_ai.tools.notebook_generator import NotebookGeneratorTool


class TestNotebookGeneratorTool:
    def test_spec(self):
        tool = NotebookGeneratorTool()
        assert tool.spec.name == "notebook_generator"
        assert tool.spec.category == "development"
        assert tool.spec.timeout_seconds == 15.0
        assert tool.spec.parameters["required"] == ["path", "cells"]

    def test_spec_cell_type_enum(self):
        tool = NotebookGeneratorTool()
        cell_schema = tool.spec.parameters["properties"]["cells"]["items"]
        assert cell_schema["properties"]["cell_type"]["enum"] == [
            "code",
            "markdown",
            "raw",
        ]
        assert cell_schema["required"] == ["cell_type", "source"]

    def test_creates_valid_notebook_from_string_source(self, tmp_path):
        f = tmp_path / "out" / "report.ipynb"
        tool = NotebookGeneratorTool()
        result = tool.execute(
            path=str(f),
            cells=[
                {"cell_type": "markdown", "source": "# Title\n\nSome text."},
                {"cell_type": "code", "source": "print('hello')"},
            ],
        )
        assert result.success is True
        assert f.exists()

        nb = json.loads(f.read_text(encoding="utf-8"))
        assert nb["nbformat"] == 4
        assert nb["nbformat_minor"] == 5
        assert len(nb["cells"]) == 2

    def test_newline_terminated_sources(self, tmp_path):
        f = tmp_path / "nb.ipynb"
        tool = NotebookGeneratorTool()
        result = tool.execute(
            path=str(f),
            cells=[
                {"cell_type": "code", "source": "x = 1\ny = 2"},
                {"cell_type": "code", "source": ["a = 3\n", "b = 4"]},
            ],
        )
        assert result.success is True
        nb = json.loads(f.read_text(encoding="utf-8"))
        for cell in nb["cells"]:
            for line in cell["source"]:
                assert line.endswith("\n")

    def test_list_source_joined_into_lines(self, tmp_path):
        f = tmp_path / "nb.ipynb"
        tool = NotebookGeneratorTool()
        result = tool.execute(
            path=str(f),
            cells=[{"cell_type": "code", "source": ["x = 1\n", "y = 2\n"]}],
        )
        assert result.success is True
        nb = json.loads(f.read_text(encoding="utf-8"))
        assert nb["cells"][0]["source"] == ["x = 1\n", "y = 2\n"]

    def test_code_cells_have_outputs_and_execution_count(self, tmp_path):
        f = tmp_path / "nb.ipynb"
        tool = NotebookGeneratorTool()
        result = tool.execute(
            path=str(f),
            cells=[
                {"cell_type": "code", "source": "1 + 1"},
                {"cell_type": "markdown", "source": "note"},
                {"cell_type": "raw", "source": "raw text"},
            ],
        )
        assert result.success is True
        nb = json.loads(f.read_text(encoding="utf-8"))
        code_cell = nb["cells"][0]
        assert code_cell["execution_count"] is None
        assert code_cell["outputs"] == []
        # Non-code cells must not carry code-only fields.
        assert "outputs" not in nb["cells"][1]
        assert "execution_count" not in nb["cells"][1]
        assert nb["cells"][2]["cell_type"] == "raw"

    def test_kernelspec_and_language_info_metadata(self, tmp_path):
        f = tmp_path / "nb.ipynb"
        tool = NotebookGeneratorTool()
        result = tool.execute(
            path=str(f),
            cells=[{"cell_type": "code", "source": "pass"}],
        )
        assert result.success is True
        nb = json.loads(f.read_text(encoding="utf-8"))
        kernelspec = nb["metadata"]["kernelspec"]
        assert kernelspec["name"] == "python3"
        assert kernelspec["language"] == "python"
        language_info = nb["metadata"]["language_info"]
        assert language_info["name"] == "python"
        assert language_info["file_extension"] == ".py"

    def test_cells_have_unique_ids(self, tmp_path):
        f = tmp_path / "nb.ipynb"
        tool = NotebookGeneratorTool()
        result = tool.execute(
            path=str(f),
            cells=[
                {"cell_type": "code", "source": "a = 1"},
                {"cell_type": "code", "source": "b = 2"},
                {"cell_type": "code", "source": "c = 3"},
            ],
        )
        assert result.success is True
        nb = json.loads(f.read_text(encoding="utf-8"))
        ids = [cell["id"] for cell in nb["cells"]]
        assert len(set(ids)) == len(ids)

    def test_metadata_reports_cell_counts(self, tmp_path):
        f = tmp_path / "nb.ipynb"
        tool = NotebookGeneratorTool()
        result = tool.execute(
            path=str(f),
            cells=[
                {"cell_type": "markdown", "source": "t"},
                {"cell_type": "code", "source": "a"},
                {"cell_type": "code", "source": "b"},
            ],
        )
        assert result.success is True
        assert result.metadata["cell_count"] == 3
        assert result.metadata["cell_types"]["code"] == 2
        assert result.metadata["nbformat"] == "4.5"

    def test_no_path(self):
        tool = NotebookGeneratorTool()
        result = tool.execute(path="", cells=[{"cell_type": "code", "source": "x"}])
        assert result.success is False
        assert "no path" in result.content.lower()

    def test_rejects_non_ipynb_path(self, tmp_path):
        tool = NotebookGeneratorTool()
        result = tool.execute(
            path=str(tmp_path / "notebook.json"),
            cells=[{"cell_type": "code", "source": "x = 1"}],
        )
        assert result.success is False
        assert ".ipynb" in result.content
        assert not (tmp_path / "notebook.json").exists()

    def test_rejects_existing_file(self, tmp_path):
        f = tmp_path / "existing.ipynb"
        f.write_text("{}", encoding="utf-8")
        tool = NotebookGeneratorTool()
        result = tool.execute(
            path=str(f),
            cells=[{"cell_type": "code", "source": "x = 1"}],
        )
        assert result.success is False
        assert "already exists" in result.content
        assert f.read_text(encoding="utf-8") == "{}"

    def test_rejects_empty_cells(self, tmp_path):
        tool = NotebookGeneratorTool()
        result = tool.execute(path=str(tmp_path / "nb.ipynb"), cells=[])
        assert result.success is False
        assert "non-empty" in result.content

    def test_rejects_unknown_cell_type(self, tmp_path):
        tool = NotebookGeneratorTool()
        result = tool.execute(
            path=str(tmp_path / "nb.ipynb"),
            cells=[{"cell_type": "javascript", "source": "console.log(1)"}],
        )
        assert result.success is False
        assert "unknown cell_type" in result.content
        assert "javascript" in result.content
        assert not (tmp_path / "nb.ipynb").exists()

    def test_rejects_missing_source(self, tmp_path):
        tool = NotebookGeneratorTool()
        result = tool.execute(
            path=str(tmp_path / "nb.ipynb"),
            cells=[{"cell_type": "code"}],
        )
        assert result.success is False
        assert "missing 'source'" in result.content

    def test_rejects_non_dict_cell(self, tmp_path):
        tool = NotebookGeneratorTool()
        result = tool.execute(
            path=str(tmp_path / "nb.ipynb"),
            cells=["print('not a dict')"],
        )
        assert result.success is False
        assert "not an object" in result.content

    def test_rejects_invalid_source_type(self, tmp_path):
        tool = NotebookGeneratorTool()
        result = tool.execute(
            path=str(tmp_path / "nb.ipynb"),
            cells=[{"cell_type": "code", "source": 42}],
        )
        assert result.success is False
        assert "source must be a string or a list of strings" in result.content
        assert not (tmp_path / "nb.ipynb").exists()

    def test_creates_parent_directories(self, tmp_path):
        f = tmp_path / "a" / "b" / "nb.ipynb"
        tool = NotebookGeneratorTool()
        result = tool.execute(
            path=str(f),
            cells=[{"cell_type": "markdown", "source": "# Deep"}],
        )
        assert result.success is True
        assert f.exists()
