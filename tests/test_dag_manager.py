import pytest

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Edge, EdgeType, Metadata, Node, NodeType


def test_dag_manager_initialization():
    metadata = Metadata(name="Test DAG", version="1.0.0")
    node = Node(
        id="00000000-0000-0000-0000-0000000000a1", type=NodeType.SYSTEM, name="System 1"
    )
    edge = Edge(
        source="00000000-0000-0000-0000-0000000000a1",
        target="00000000-0000-0000-0000-0000000000a1",
        type=EdgeType.CALLS,
    )

    manager = DAGManager(metadata, [node], [edge])
    assert manager.metadata.name == "Test DAG"
    assert "00000000-0000-0000-0000-0000000000a1" in manager.nodes
    assert len(manager.edges) == 1


def test_dag_manager_add_node():
    manager = DAGManager(Metadata(name="Test", version="1.0"), [], [])
    node = Node(
        id="00000000-0000-0000-0000-0000000000a1", type=NodeType.SYSTEM, name="Sys1"
    )
    manager.add_node(node)

    assert "00000000-0000-0000-0000-0000000000a1" in manager.nodes

    with pytest.raises(ValueError, match="already exists"):
        manager.add_node(node)


def test_dag_manager_remove_node():
    node1 = Node(
        id="00000000-0000-0000-0000-0000000000a1", type=NodeType.SYSTEM, name="Sys1"
    )
    node2 = Node(
        id="00000000-0000-0000-0000-0000000000a2", type=NodeType.SYSTEM, name="Sys2"
    )
    edge = Edge(
        source="00000000-0000-0000-0000-0000000000a1",
        target="00000000-0000-0000-0000-0000000000a2",
        type=EdgeType.CALLS,
    )
    manager = DAGManager(Metadata(name="Test", version="1.0"), [node1, node2], [edge])

    manager.remove_node("00000000-0000-0000-0000-0000000000a1")
    assert "00000000-0000-0000-0000-0000000000a1" not in manager.nodes
    assert len(manager.edges) == 0


def test_dag_manager_update_node():
    node1 = Node(
        id="00000000-0000-0000-0000-0000000000a1", type=NodeType.SYSTEM, name="Sys1"
    )
    manager = DAGManager(Metadata(name="Test", version="1.0"), [node1], [])
    manager.update_node(
        "00000000-0000-0000-0000-0000000000a1", name="Updated Sys1", domain="test"
    )

    n = manager.get_node("00000000-0000-0000-0000-0000000000a1")
    assert n.name == "Updated Sys1"
    assert n.domain == "test"


def test_dag_manager_add_edge():
    node1 = Node(
        id="00000000-0000-0000-0000-0000000000a1", type=NodeType.SYSTEM, name="Sys1"
    )
    node2 = Node(
        id="00000000-0000-0000-0000-0000000000a2", type=NodeType.SYSTEM, name="Sys2"
    )
    manager = DAGManager(Metadata(name="Test", version="1.0"), [node1, node2], [])

    edge = Edge(
        source="00000000-0000-0000-0000-0000000000a1",
        target="00000000-0000-0000-0000-0000000000a2",
        type=EdgeType.CALLS,
    )
    manager.add_edge(edge)
    assert len(manager.edges) == 1

    with pytest.raises(
        ValueError,
    ):
        manager.add_edge(
            Edge(
                source="ff7f1bc1-779a-4461-ab2f-71d0ed4a6afa",
                target="00000000-0000-0000-0000-0000000000a2",
                type=EdgeType.CALLS,
            )
        )


def test_dag_manager_remove_edge():
    node1 = Node(
        id="00000000-0000-0000-0000-0000000000a1", type=NodeType.SYSTEM, name="Sys1"
    )
    node2 = Node(
        id="00000000-0000-0000-0000-0000000000a2", type=NodeType.SYSTEM, name="Sys2"
    )
    edge = Edge(
        source="00000000-0000-0000-0000-0000000000a1",
        target="00000000-0000-0000-0000-0000000000a2",
        type=EdgeType.CALLS,
    )
    manager = DAGManager(Metadata(name="Test", version="1.0"), [node1, node2], [edge])

    manager.remove_edge(
        "00000000-0000-0000-0000-0000000000a1",
        "00000000-0000-0000-0000-0000000000a2",
        EdgeType.CALLS,
    )
    assert len(manager.edges) == 0


def test_cycle_detection():
    node1 = Node(
        id="00000000-0000-0000-0000-0000000000a1", type=NodeType.SYSTEM, name="Sys1"
    )
    node2 = Node(
        id="00000000-0000-0000-0000-0000000000a2", type=NodeType.SYSTEM, name="Sys2"
    )
    node3 = Node(
        id="00000000-0000-0000-0000-0000000000a3", type=NodeType.SYSTEM, name="Sys3"
    )

    # n1 -> n2 -> n3
    edge1 = Edge(
        source="00000000-0000-0000-0000-0000000000a1",
        target="00000000-0000-0000-0000-0000000000a2",
        type=EdgeType.DEPENDS_ON,
    )
    edge2 = Edge(
        source="00000000-0000-0000-0000-0000000000a2",
        target="00000000-0000-0000-0000-0000000000a3",
        type=EdgeType.DEPENDS_ON,
    )

    manager = DAGManager(
        Metadata(name="Test", version="1.0"), [node1, node2, node3], [edge1, edge2]
    )
    manager.validate()  # Should not raise

    # n3 -> n1 (cycle)
    edge3 = Edge(
        source="00000000-0000-0000-0000-0000000000a3",
        target="00000000-0000-0000-0000-0000000000a1",
        type=EdgeType.DEPENDS_ON,
    )
    with pytest.raises(ValueError, match="Cycle detected"):
        manager.add_edge(edge3)


def test_find_nodes():
    node1 = Node(
        id="00000000-0000-0000-0000-0000000000a1",
        type=NodeType.SYSTEM,
        name="Sys1",
        domain="core",
    )
    node2 = Node(
        id="00000000-0000-0000-0000-0000000000a2",
        type=NodeType.CONTAINER,
        name="Cont1",
        domain="core",
    )
    node3 = Node(
        id="00000000-0000-0000-0000-0000000000a3",
        type=NodeType.SYSTEM,
        name="Sys2",
        domain="other",
    )
    manager = DAGManager(
        Metadata(name="Test", version="1.0"), [node1, node2, node3], []
    )

    res = manager.find_nodes(domain="core")
    assert len(res) == 2

    res = manager.find_nodes(type=NodeType.SYSTEM)
    assert len(res) == 2

    res = manager.find_nodes(type=NodeType.SYSTEM, domain="core")
    assert len(res) == 1
    assert res[0].id == "00000000-0000-0000-0000-0000000000a1"
