import pytest

from src.utils.markdown_parser import extract_h2


def test_extract_h2_with_valid_markdown(tmp_path):
    md_file = tmp_path / "test.md"
    md_file.write_text("# H1\n## H2 1\ntext\n## H2 2\n### H3\n", encoding="utf-8")
    result = extract_h2(str(md_file))
    assert result == ["## H2 1", "## H2 2"]


def test_extract_h2_no_h2_headers(tmp_path):
    md_file = tmp_path / "test.md"
    md_file.write_text("# H1\n### H3\n", encoding="utf-8")
    result = extract_h2(str(md_file))
    assert result == []


def test_extract_h2_empty_file(tmp_path):
    md_file = tmp_path / "test.md"
    md_file.write_text("", encoding="utf-8")
    result = extract_h2(str(md_file))
    assert result == []


def test_extract_h2_file_not_found():
    with pytest.raises(FileNotFoundError):
        extract_h2("nonexistent.md")
