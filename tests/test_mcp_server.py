import json
import os
from pathlib import Path

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Metadata, Node, NodeType
from aio_agentic_sdlc.mcp_server import generate_document, reconcile_dags


def test_mcp_generate_document(tmp_path):
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()

    template_content = (
        "Title: {{ title }}\nAuthor: {{ author }}\nContent: {{ content }}"
    )
    template_file = templates_dir / "test-template.md"
    template_file.write_text(template_content, encoding="utf-8")

    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        data = {
            "title": "Test MCP Title",
            "author": "MCP",
            "content": "This is an MCP test.",
        }
        data_json = json.dumps(data)

        result = generate_document(
            template_name="test-template.md",
            data_json=data_json,
            output_filename="mcp_output.md",
            target_dir=str(tmp_path),
        )

        assert "successfully generated" in result

        output_file = tmp_path / "mcp_output.md"
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert "Title: Test MCP Title" in content
        assert "Author: MCP" in content
        assert "Content: This is an MCP test." in content
    finally:
        os.chdir(old_cwd)


def test_mcp_generate_document_error(tmp_path):
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        # Create templates dir so we don't get directory not found
        (tmp_path / "templates").mkdir()

        result = generate_document(
            template_name="missing.md",
            data_json="{}",
            output_filename="mcp_out.md",
            target_dir=str(tmp_path),
        )
        assert "Error generating document" in result
        assert "Template 'missing.md' not found" in result
    finally:
        os.chdir(old_cwd)


def test_mcp_generate_document_uses_explicit_project_path(tmp_path):
    project = tmp_path / "project"
    process_cwd = tmp_path / "plugin-cache"
    (project / "templates").mkdir(parents=True)
    process_cwd.mkdir()
    (project / "templates" / "test-template.md").write_text(
        "Project: {{ name }}", encoding="utf-8"
    )

    old_cwd = Path.cwd()
    os.chdir(process_cwd)
    try:
        result = generate_document(
            template_name="test-template.md",
            data_json=json.dumps({"name": "Codex"}),
            output_filename="generated.md",
            target_dir=str(project / "specs"),
            project_path=str(project),
        )
    finally:
        os.chdir(old_cwd)

    assert "successfully generated" in result
    assert (project / "specs" / "generated.md").read_text(encoding="utf-8") == (
        "Project: Codex"
    )


def test_mcp_reconcile_dags_returns_the_same_evidence_report(tmp_path):
    node = Node(
        id="00000000-0000-0000-0000-000000000001",
        type=NodeType.COMPONENT,
        name="Mapped component",
    )
    metadata = Metadata(name="Test", version="1.0")
    DAGManager(metadata, [node], []).save(str(tmp_path / "intention-dag.yaml"))
    DAGManager(metadata, [node], []).save(str(tmp_path / "reality-dag.yaml"))

    result = json.loads(reconcile_dags(project_path=str(tmp_path), max_items=10))

    assert result["schema_version"] == 1
    assert result["summary"]["confirmed"] == 1
    assert result["items"][0]["evidence"] == [
        {
            "kind": "canonical_guid",
            "value": "00000000-0000-0000-0000-000000000001",
        }
    ]
