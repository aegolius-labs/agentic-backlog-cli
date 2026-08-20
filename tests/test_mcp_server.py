import json
import os
from pathlib import Path

from click.testing import CliRunner

from aio_agentic_sdlc.dag_cli import cli
from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Edge, EdgeType, Metadata, Node, NodeType
from aio_agentic_sdlc.mcp_server import (
    approve_mapping,
    generate_document,
    reconcile_dags,
    review_mapping,
    triage_reconciliation_drift,
    visualize_dag,
)
from aio_agentic_sdlc.workspace import (
    CHANGES_DIR,
    INTENTION_DAG_FILE,
    REALITY_DAG_FILE,
    SPECS_DIR,
)


def _sdd_data(title="Test MCP Title"):
    return {
        "title": title,
        "author": "MCP",
        "date": "2026-08-10",
        "related_prd": "prd.md",
        "architecture_overview": "Overview",
        "system_components": "Components",
        "data_model": "Model",
        "api_design": "API",
        "security_considerations": "Security",
    }


def test_mcp_generate_document(tmp_path):
    result = generate_document(
        template_name="sdd-template.md",
        data_json=json.dumps(_sdd_data()),
        output_filename="mcp_output.md",
        target_dir=str(tmp_path),
        project_path=str(tmp_path),
    )

    assert "successfully generated" in result
    content = (tmp_path / "mcp_output.md").read_text(encoding="utf-8")
    assert "# Test MCP Title" in content
    assert 'author: "MCP"' in content


def test_mcp_generate_document_error(tmp_path):
    result = generate_document(
        template_name="missing.md",
        data_json="{}",
        output_filename="mcp_out.md",
        target_dir=str(tmp_path),
        project_path=str(tmp_path),
    )
    assert "Error generating document" in result
    assert "Template 'missing.md' not found" in result


def test_mcp_generate_document_uses_explicit_project_path(tmp_path):
    project = tmp_path / "project"
    process_cwd = tmp_path / "plugin-cache"
    project.mkdir()
    process_cwd.mkdir()

    old_cwd = Path.cwd()
    os.chdir(process_cwd)
    try:
        result = generate_document(
            template_name="sdd-template.md",
            data_json=json.dumps(_sdd_data("Codex Workspace")),
            output_filename="generated.md",
            target_dir=str(project / SPECS_DIR),
            project_path=str(project),
        )
    finally:
        os.chdir(old_cwd)

    assert "successfully generated" in result
    assert "# Codex Workspace" in (project / SPECS_DIR / "generated.md").read_text(
        encoding="utf-8"
    )


def test_mcp_generate_document_defaults_to_framework_changes(tmp_path):
    result = generate_document(
        template_name="sdd-template.md",
        data_json=json.dumps(_sdd_data("Default Target")),
        output_filename="generated.md",
        project_path=str(tmp_path),
    )

    assert "successfully generated" in result
    assert (tmp_path / CHANGES_DIR / "generated.md").is_file()


def test_mcp_reconcile_dags_returns_the_same_evidence_report(tmp_path):
    node = Node(
        id="00000000-0000-0000-0000-000000000001",
        type=NodeType.COMPONENT,
        name="Mapped component",
    )
    metadata = Metadata(name="Test", version="1.0")
    (tmp_path / INTENTION_DAG_FILE).parent.mkdir(parents=True)
    DAGManager(metadata, [node], []).save(str(tmp_path / INTENTION_DAG_FILE))
    DAGManager(metadata, [node], []).save(str(tmp_path / REALITY_DAG_FILE))

    result = json.loads(reconcile_dags(project_path=str(tmp_path)))

    assert result["schema_version"] == 1
    assert result["summary"]["confirmed"] == 1
    assert result["items"][0]["evidence"] == [
        {
            "kind": "canonical_guid",
            "value": "00000000-0000-0000-0000-000000000001",
        }
    ]


def test_mcp_triage_reconciliation_drift_withholds_unapproved_intent(tmp_path):
    node = Node(
        id="00000000-0000-0000-0000-000000000002",
        type=NodeType.COMPONENT,
        name="Unapproved capability",
    )
    metadata = Metadata(name="Test", version="1.0")
    (tmp_path / INTENTION_DAG_FILE).parent.mkdir(parents=True)
    DAGManager(metadata, [node], []).save(str(tmp_path / INTENTION_DAG_FILE))
    DAGManager(metadata, [], []).save(str(tmp_path / REALITY_DAG_FILE))

    result = json.loads(triage_reconciliation_drift(project_path=str(tmp_path)))

    assert result["schema_version"] == 1
    assert result["summary"]["obsolete_or_unapproved_intent"] == 1
    assert result["summary"]["actionable_implementation"] == 0
    assert result["items"][0]["decision_source"] == "approval_gate"


def test_mcp_visualize_matches_cli_and_never_mutates_state(tmp_path):
    first = "00000000-0000-0000-0000-000000000001"
    second = "00000000-0000-0000-0000-000000000002"
    metadata = Metadata(name="Visualization", version="1.0")
    nodes = [
        Node(id=first, type=NodeType.COMPONENT, name="First"),
        Node(id=second, type=NodeType.COMPONENT, name="Second"),
    ]
    edges = [Edge(source=first, target=second, type=EdgeType.CALLS)]
    intention_path = tmp_path / INTENTION_DAG_FILE
    reality_path = tmp_path / REALITY_DAG_FILE
    intention_path.parent.mkdir(parents=True)
    DAGManager(metadata, nodes, edges).save(str(intention_path))
    DAGManager(metadata, nodes, edges).save(str(reality_path))
    before = (intention_path.read_bytes(), reality_path.read_bytes())

    cli_result = CliRunner().invoke(
        cli,
        [
            "visualize",
            "--project-path",
            str(tmp_path),
            "--view",
            "comparison",
            "--depth",
            "0",
            "--max-items",
            "1",
            "--max-edges",
            "1",
            "--max-candidates",
            "1",
            "--format",
            "json",
        ],
    )
    mcp_result = visualize_dag(
        project_path=str(tmp_path),
        view="comparison",
        depth=0,
        max_items=1,
        max_edges=1,
        max_candidates=1,
        output_format="json",
    )

    assert cli_result.exit_code == 0
    assert json.loads(mcp_result) == json.loads(cli_result.output)
    assert (intention_path.read_bytes(), reality_path.read_bytes()) == before


def test_mcp_visualize_reports_argument_errors(tmp_path):
    metadata = Metadata(name="Visualization", version="1.0")
    intention_path = tmp_path / INTENTION_DAG_FILE
    intention_path.parent.mkdir(parents=True)
    DAGManager(metadata, [], []).save(str(intention_path))
    DAGManager(metadata, [], []).save(str(tmp_path / REALITY_DAG_FILE))

    assert "Unsupported view" in visualize_dag(project_path=str(tmp_path), view="raw")
    assert "max_edges must be at least 1" in visualize_dag(
        project_path=str(tmp_path), max_edges=0
    )
    assert "Unsupported output format" in visualize_dag(
        project_path=str(tmp_path), output_format="yaml"
    )


def test_mcp_mapping_review_and_approval_use_source_bound_evidence(tmp_path):
    intent_id = "6506870b-b262-4f54-b6e9-43de4a873a55"
    source_path = tmp_path / "src" / "archiver.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("class PRDArchiver:\n    pass\n", encoding="utf-8")
    (tmp_path / INTENTION_DAG_FILE).parent.mkdir(parents=True)
    DAGManager(
        Metadata(name="Mapping MCP", version="1.0"),
        [Node(id=intent_id, type=NodeType.COMPONENT, name="PRD Archiver")],
        [],
    ).save(str(tmp_path / INTENTION_DAG_FILE))

    review = json.loads(review_mapping(intent_id=intent_id, project_path=str(tmp_path)))
    candidate_id = review["candidates"][0]["reality"]["id"]
    result = json.loads(
        approve_mapping(
            intent_id=intent_id,
            candidate_reality_id=candidate_id,
            evidence_digest=review["evidence_digest"],
            approved_by="Felix",
            approved_at="2026-08-07T21:30:00+00:00",
            rationale="Reviewed exact MCP evidence.",
            project_path=str(tmp_path),
        )
    )

    assert result["postcondition"]["classification"] == "confirmed"
    assert result["receipt"]["evidence_digest"] == review["evidence_digest"]
    assert f"# aio-sdlc-node: {intent_id}" in source_path.read_text(encoding="utf-8")
