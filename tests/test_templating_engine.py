import os
from pathlib import Path

import pytest

from aio_agentic_sdlc.templating_engine import generate_document


def test_generate_document(tmp_path):
    # Use tmp_path to create a dummy template directory
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()

    template_content = (
        "Title: {{ title }}\nAuthor: {{ author }}\nContent: {{ content }}"
    )
    template_file = templates_dir / "test-template.md"
    template_file.write_text(template_content, encoding="utf-8")

    # Temporarily change cwd to tmp_path so the templating engine finds our templates/
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        data = {"title": "Test Title", "author": "Alice", "content": "This is a test."}
        output_file = tmp_path / "output.md"

        result = generate_document("test-template.md", data, str(output_file))

        assert "Title: Test Title" in result
        assert "Author: Alice" in result
        assert "Content: This is a test." in result

        assert output_file.exists()
        assert output_file.read_text(encoding="utf-8") == result
    finally:
        os.chdir(old_cwd)


def test_template_not_found(tmp_path):
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        # Create templates dir so we don't get directory not found
        (tmp_path / "templates").mkdir()

        with pytest.raises(FileNotFoundError, match="Template 'missing.md' not found"):
            generate_document("missing.md", {}, "out.md")
    finally:
        os.chdir(old_cwd)


def test_generate_document_preserves_template_trailing_newline(tmp_path):
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "report.md").write_text(
        "# {{ title }}\n",
        encoding="utf-8",
    )

    rendered = generate_document(
        "report.md",
        {"title": "Evidence"},
        str(tmp_path / "report.md"),
        templates_dir=str(templates_dir),
    )

    assert rendered == "# Evidence\n"
    assert (tmp_path / "report.md").read_bytes().endswith(b"\n")
