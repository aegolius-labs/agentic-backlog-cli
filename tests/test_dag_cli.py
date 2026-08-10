import json

import pytest
from click.testing import CliRunner

from aio_agentic_sdlc.dag_cli import cli
from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Edge, EdgeType, Metadata, Node, NodeType


@pytest.fixture
def sample_dag_file(tmp_path):
    metadata = Metadata(name="Test DAG", version="1.0.0")
    node1 = Node(
        id="00000000-0000-0000-0000-0000000000a1",
        type=NodeType.SYSTEM,
        name="System 1",
        domain="core",
    )
    node2 = Node(
        id="00000000-0000-0000-0000-0000000000a2",
        type=NodeType.SYSTEM,
        name="System 2",
        domain="core",
    )
    edge = Edge(
        source="00000000-0000-0000-0000-0000000000a1",
        target="00000000-0000-0000-0000-0000000000a2",
        type=EdgeType.CALLS,
    )

    manager = DAGManager(metadata, [node1, node2], [edge])
    filepath = tmp_path / "dag.yaml"
    manager.save(str(filepath))
    return str(filepath)


def test_cli_validate(sample_dag_file):
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "--file", sample_dag_file])
    assert result.exit_code == 0
    assert "DAG is valid." in result.output


def test_cli_node_add(sample_dag_file):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "node",
            "add",
            "--file",
            sample_dag_file,
            "--id",
            "00000000-0000-0000-0000-0000000000a3",
            "--type",
            "module",
            "--name",
            "Module 3",
            "--domain",
            "users",
        ],
    )
    assert result.exit_code == 0

    manager = DAGManager.load(sample_dag_file)
    assert "00000000-0000-0000-0000-0000000000a3" in manager.nodes
    assert (
        manager.get_node("00000000-0000-0000-0000-0000000000a3").type == NodeType.MODULE
    )
    assert manager.get_node("00000000-0000-0000-0000-0000000000a3").name == "Module 3"


def test_cli_node_update(sample_dag_file):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "node",
            "update",
            "--file",
            sample_dag_file,
            "--id",
            "00000000-0000-0000-0000-0000000000a1",
            "--description",
            "Updated desc",
        ],
    )
    assert result.exit_code == 0

    manager = DAGManager.load(sample_dag_file)
    assert (
        manager.get_node("00000000-0000-0000-0000-0000000000a1").description
        == "Updated desc"
    )


def test_cli_node_remove(sample_dag_file):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "node",
            "remove",
            "--file",
            sample_dag_file,
            "--id",
            "00000000-0000-0000-0000-0000000000a2",
        ],
    )
    assert result.exit_code == 0

    manager = DAGManager.load(sample_dag_file)
    assert "00000000-0000-0000-0000-0000000000a2" not in manager.nodes
    assert len(manager.edges) == 0


def test_cli_node_list(sample_dag_file):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "node",
            "list",
            "--file",
            sample_dag_file,
            "--domain",
            "core",
            "--output",
            "json",
        ],
    )
    assert result.exit_code == 0

    data = json.loads(result.output)
    assert len(data) == 2
    assert data[0]["id"] in [
        "00000000-0000-0000-0000-0000000000a1",
        "00000000-0000-0000-0000-0000000000a2",
    ]


def test_cli_edge_add(sample_dag_file):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "edge",
            "add",
            "--file",
            sample_dag_file,
            "--source",
            "00000000-0000-0000-0000-0000000000a2",
            "--target",
            "00000000-0000-0000-0000-0000000000a1",
            "--type",
            "writes",
        ],
    )
    assert result.exit_code == 0

    manager = DAGManager.load(sample_dag_file)
    assert len(manager.edges) == 2
    assert manager.edges[1].source == "00000000-0000-0000-0000-0000000000a2"


def test_cli_edge_remove(sample_dag_file):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "edge",
            "remove",
            "--file",
            sample_dag_file,
            "--source",
            "00000000-0000-0000-0000-0000000000a1",
            "--target",
            "00000000-0000-0000-0000-0000000000a2",
            "--type",
            "calls",
        ],
    )
    assert result.exit_code == 0

    manager = DAGManager.load(sample_dag_file)
    assert len(manager.edges) == 0


def test_cli_reconcile_returns_bounded_read_only_report(sample_dag_file, tmp_path):
    reality_file = tmp_path / "reality.yaml"
    DAGManager.load(sample_dag_file).save(str(reality_file))
    before_intention = (tmp_path / "dag.yaml").read_bytes()
    before_reality = reality_file.read_bytes()

    result = CliRunner().invoke(
        cli,
        [
            "reconcile",
            "--intention",
            sample_dag_file,
            "--reality",
            str(reality_file),
            "--max-items",
            "1",
        ],
    )

    assert result.exit_code == 0
    report = json.loads(result.output)
    assert report["summary"]["confirmed"] == 2
    assert report["limit"] == {
        "max_items": 1,
        "total_items": 2,
        "returned_items": 1,
        "truncated": True,
    }
    assert (tmp_path / "dag.yaml").read_bytes() == before_intention
    assert reality_file.read_bytes() == before_reality


def test_cli_reconcile_can_write_a_reproducible_report_artifact(
    sample_dag_file, tmp_path
):
    reality_file = tmp_path / "reality.yaml"
    report_file = tmp_path / "reconciliation-report.json"
    DAGManager.load(sample_dag_file).save(str(reality_file))

    result = CliRunner().invoke(
        cli,
        [
            "reconcile",
            "--intention",
            sample_dag_file,
            "--reality",
            str(reality_file),
            "--max-items",
            "1",
            "--output",
            str(report_file),
        ],
    )

    assert result.exit_code == 0
    assert result.output.strip() == f"Reconciliation report saved to {report_file}."
    report = json.loads(report_file.read_text(encoding="utf-8"))
    assert report["summary"]["confirmed"] == 2
    assert report["limit"]["truncated"] is True


@pytest.mark.parametrize("protected_target", ["intention", "reality"])
def test_cli_reconcile_refuses_to_overwrite_input_dags(
    sample_dag_file, tmp_path, protected_target
):
    intention_file = tmp_path / "dag.yaml"
    reality_file = tmp_path / "reality.yaml"
    DAGManager.load(sample_dag_file).save(str(reality_file))
    before_intention = intention_file.read_bytes()
    before_reality = reality_file.read_bytes()
    output = intention_file if protected_target == "intention" else reality_file

    result = CliRunner().invoke(
        cli,
        [
            "reconcile",
            "--intention",
            str(intention_file),
            "--reality",
            str(reality_file),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 1
    assert "protected framework state" in result.output
    assert intention_file.read_bytes() == before_intention
    assert reality_file.read_bytes() == before_reality


@pytest.mark.parametrize(
    "state_filename",
    ["backlog.json", "state-audit.jsonl", "state.lock"],
)
def test_cli_reconcile_refuses_to_overwrite_versioned_state(
    sample_dag_file, tmp_path, state_filename
):
    reality_file = tmp_path / "reality.yaml"
    state_file = tmp_path / state_filename
    DAGManager.load(sample_dag_file).save(str(reality_file))
    state_file.write_text('{"schema_version": 2}\n', encoding="utf-8")
    before_state = state_file.read_bytes()

    result = CliRunner().invoke(
        cli,
        [
            "reconcile",
            "--intention",
            sample_dag_file,
            "--reality",
            str(reality_file),
            "--output",
            str(state_file),
        ],
    )

    assert result.exit_code == 1
    assert "protected framework state" in result.output
    assert state_file.read_bytes() == before_state


def test_cli_mapping_review_and_approve_use_the_same_fresh_evidence(tmp_path):
    intent_id = "6506870b-b262-4f54-b6e9-43de4a873a55"
    source_path = tmp_path / "src" / "archiver.py"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("class PRDArchiver:\n    pass\n", encoding="utf-8")
    DAGManager(
        Metadata(name="Mapping CLI", version="1.0"),
        [Node(id=intent_id, type=NodeType.COMPONENT, name="PRD Archiver")],
        [],
    ).save(str(tmp_path / "intention-dag.yaml"))
    runner = CliRunner()

    review_result = runner.invoke(
        cli,
        [
            "mapping",
            "review",
            "--project-path",
            str(tmp_path),
            "--intent-id",
            intent_id,
        ],
    )

    assert review_result.exit_code == 0
    review = json.loads(review_result.output)
    candidate_id = review["candidates"][0]["reality"]["id"]

    approve_result = runner.invoke(
        cli,
        [
            "mapping",
            "approve",
            "--project-path",
            str(tmp_path),
            "--intent-id",
            intent_id,
            "--candidate-reality-id",
            candidate_id,
            "--evidence-digest",
            review["evidence_digest"],
            "--approved-by",
            "Felix",
            "--approved-at",
            "2026-08-07T21:30:00+00:00",
            "--rationale",
            "Reviewed exact CLI evidence.",
        ],
    )

    assert approve_result.exit_code == 0
    approval = json.loads(approve_result.output)
    assert approval["postcondition"]["classification"] == "confirmed"
    assert f"# aio-sdlc-node: {intent_id}" in source_path.read_text(encoding="utf-8")


def test_cli_diff_is_safe_by_default_and_legacy_is_explicit(sample_dag_file, tmp_path):
    reality_file = tmp_path / "empty-reality.yaml"
    DAGManager(Metadata(name="Reality", version="1.0"), [], []).save(str(reality_file))
    runner = CliRunner()

    safe_result = runner.invoke(
        cli,
        [
            "diff",
            "--intention",
            sample_dag_file,
            "--reality",
            str(reality_file),
        ],
    )
    legacy_result = runner.invoke(
        cli,
        [
            "diff",
            "--intention",
            sample_dag_file,
            "--reality",
            str(reality_file),
            "--mode",
            "legacy-structural",
        ],
    )

    assert safe_result.exit_code == 0
    safe = json.loads(safe_result.output)
    assert safe["meta"]["mode"] == "safe"
    assert not any(name.startswith("Create ") for name in safe["nodes"])

    assert legacy_result.exit_code == 0
    legacy = json.loads(legacy_result.output)
    assert "Create System 'System 1'" in legacy["nodes"]
