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
