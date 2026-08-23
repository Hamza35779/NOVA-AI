from __future__ import annotations

from unittest.mock import MagicMock, patch

from nova_ai.tools.web_readability import (
    WebReadabilityTool,
    _clean_html_to_markdown,
    _convert_table_to_markdown,
)


def test_clean_html_to_markdown_basic() -> None:
    html_raw = """
    <html>
    <head><title>Test Article</title></head>
    <body>
        <nav><a href="/home">Home</a></nav>
        <article>
            <h1>Main Title</h1>
            <p>This is the <b>first paragraph</b> with <a href="https://example.com">a link</a>.</p>
            <pre><code>print("hello")</code></pre>
            <ul>
                <li>Item 1</li>
                <li>Item 2</li>
            </ul>
        </article>
        <footer>Copyright 2026</footer>
    </body>
    </html>
    """
    md = _clean_html_to_markdown(html_raw)
    assert "# Main Title" in md
    assert "**first paragraph**" in md
    assert "[a link](https://example.com)" in md
    assert '```\nprint("hello")\n```' in md
    assert "* Item 1" in md
    assert "* Item 2" in md
    assert "Copyright" not in md
    assert "Home" not in md


def test_convert_table_to_markdown() -> None:
    table_html = """
    <table>
        <tr><th>Name</th><th>Role</th></tr>
        <tr><td>Alice</td><td>Engineer</td></tr>
        <tr><td>Bob</td><td>Designer</td></tr>
    </table>
    """
    md_table = _convert_table_to_markdown(table_html)
    assert "| Name | Role |" in md_table
    assert "| --- | --- |" in md_table
    assert "| Alice | Engineer |" in md_table
    assert "| Bob | Designer |" in md_table


def test_web_readability_spec() -> None:
    tool = WebReadabilityTool()
    spec = tool.spec
    assert spec.name == "web_readability"
    assert spec.category == "retrieval"
    assert "url" in spec.parameters["required"]


@patch("nova_ai.tools.web_readability.check_ssrf")
@patch("httpx.Client")
def test_web_readability_execute_success(
    mock_client_cls: MagicMock, mock_ssrf: MagicMock
) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><head><title>Sample Post</title></head><body><article><p>Hello World Content</p></article></body></html>"

    mock_client_instance = MagicMock()
    mock_client_instance.get.return_value = mock_response
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_client_cls.return_value = mock_client_instance

    tool = WebReadabilityTool()
    result = tool.execute(url="https://example.com/post")

    assert result.success is True
    assert "# Sample Post" in result.content
    assert "Hello World Content" in result.content
    assert result.metadata["status_code"] == 200
