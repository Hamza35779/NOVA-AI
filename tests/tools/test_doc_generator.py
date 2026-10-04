from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from nova_ai.tools.doc_generator import DocumentGeneratorTool


def test_document_generator_docx() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tool = DocumentGeneratorTool()
        result = tool.execute(
            doc_type="docx",
            title="Quarterly Review",
            filename="Quarterly_Review.docx",
            sections_or_slides=[
                {
                    "heading": "Executive Summary",
                    "body": "Strong performance across metrics.",
                    "bullets": ["Revenue +20%", "Retention 95%"],
                }
            ],
            output_dir=tmpdir,
        )
        assert result.success is True, result.content
        assert "Quarterly_Review" in result.content
        out_path = Path(tmpdir)
        assert (out_path / "Quarterly_Review.docx").exists()
        assert result.metadata["file_path"].endswith(".docx")


def test_document_generator_pptx() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tool = DocumentGeneratorTool()
        result = tool.execute(
            doc_type="pptx",
            title="Product Architecture",
            filename="Product_Architecture.pptx",
            sections_or_slides=[
                {
                    "title": "Introduction",
                    "body": "Overview of the system.",
                    "bullets": ["Microservices", "Low latency", "High availability"],
                }
            ],
            output_dir=tmpdir,
        )
        assert result.success is True, result.content
        assert "Product_Architecture" in result.content
        out_path = Path(tmpdir)
        assert (out_path / "Product_Architecture.pptx").exists()
        assert result.metadata["file_path"].endswith(".pptx")


def test_document_generator_pdf() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        tool = DocumentGeneratorTool()
        result = tool.execute(
            doc_type="pdf",
            title="Network Report",
            filename="Network_Report.pdf",
            sections_or_slides=[
                {
                    "heading": "Findings",
                    "body": "Latency within SLO.",
                    "bullets": ["p99 120ms", "Error rate 0.1%"],
                }
            ],
            output_dir=tmpdir,
        )
        assert result.success is True, result.content
        assert "Network_Report" in result.content
        out_path = Path(tmpdir)
        assert (out_path / "Network_Report.pdf").exists()
        assert result.metadata["file_path"].endswith(".pdf")


@pytest.mark.parametrize(
    ("doc_type", "filename", "module"),
    [
        ("docx", "Report.docx", "docx"),
        ("pptx", "Deck.pptx", "pptx"),
        ("pdf", "Report.pdf", "reportlab"),
    ],
)
def test_missing_doc_library_fails_with_install_hint(
    monkeypatch: pytest.MonkeyPatch, doc_type: str, filename: str, module: str
) -> None:
    # Drop any cached submodules (e.g. reportlab.lib from an earlier native
    # test in this process) so the poisoned parent package is actually hit.
    for key in [
        k
        for k in sys.modules
        if k == module or k.startswith(module + ".")
    ]:
        monkeypatch.delitem(sys.modules, key, raising=False)
    monkeypatch.setitem(sys.modules, module, None)
    with tempfile.TemporaryDirectory() as tmpdir:
        tool = DocumentGeneratorTool()
        result = tool.execute(
            doc_type=doc_type,
            title="Test Doc",
            filename=filename,
            sections_or_slides=[{"heading": "S", "body": "B"}],
            output_dir=tmpdir,
        )
    assert result.success is False
    assert "doc-gen" in result.content
    assert "uv pip install" in result.content
    assert result.metadata["missing_package"]


def test_document_generator_empty_title_rejected() -> None:
    tool = DocumentGeneratorTool()
    result = tool.execute(doc_type="docx", title="", filename="test.docx")
    assert result.success is False
    assert "title is required" in result.content


def test_document_generator_unsupported_format() -> None:
    tool = DocumentGeneratorTool()
    result = tool.execute(doc_type="xlsx", title="Test", filename="test.xlsx")
    assert result.success is False
    assert "Unsupported" in result.content
