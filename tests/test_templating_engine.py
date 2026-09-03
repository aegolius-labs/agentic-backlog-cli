import os

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

    data = {"title": "Test Title", "author": "Alice", "content": "This is a test."}
    output_file = tmp_path / "output.md"

    result = generate_document(
        "test-template.md",
        data,
        str(output_file),
        templates_dir=str(templates_dir),
    )

    assert "Title: Test Title" in result
    assert "Author: Alice" in result
    assert "Content: This is a test." in result

    assert output_file.exists()
    assert output_file.read_text(encoding="utf-8") == result


def test_template_not_found(tmp_path):
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="Template 'missing.md' not found"):
        generate_document("missing.md", {}, "out.md", templates_dir=str(templates_dir))


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


def test_generate_document_rejects_symlinked_output_without_external_write(tmp_path):
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "report.md").write_text("# {{ title }}\n", encoding="utf-8")
    external = tmp_path / "external.md"
    external.write_text("preserve", encoding="utf-8")
    output = tmp_path / "output.md"
    try:
        os.symlink(external, output)
    except OSError as error:
        pytest.skip(f"Symlink creation unavailable: {error}")

    with pytest.raises(ValueError, match="regular file"):
        generate_document(
            "report.md",
            {"title": "escaped"},
            str(output),
            templates_dir=str(templates_dir),
        )

    assert external.read_text(encoding="utf-8") == "preserve"
