from __future__ import annotations

import tempfile
from pathlib import Path

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
        assert result.success is True
        assert "Quarterly_Review" in result.content
        out_path = Path(tmpdir)
        assert (out_path / "Quarterly_Review.docx").exists() or (
            out_path / "Quarterly_Review.md"
        ).exists()


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
        assert result.success is True
        assert "Product_Architecture" in result.content


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
