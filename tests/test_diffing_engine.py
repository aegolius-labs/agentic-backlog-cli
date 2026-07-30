from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Edge, EdgeType, Metadata, Node, NodeType
from aio_agentic_sdlc.diffing_engine import DiffingEngine, DiffPolicy


def create_sample_dag(name="Sample", nodes=None, edges=None):
    if nodes is None:
        nodes = []
    if edges is None:
        edges = []
    meta = Metadata(name=name, version="1.0")
    return DAGManager(meta, nodes, edges)


def create_legacy_engine(intent, reality):
    """Exercise the compatibility algorithm explicitly; safe mode is tested separately."""

    return DiffingEngine(
        intent,
        reality,
        policy=DiffPolicy.legacy_structural(),
    )


def test_missing_node():
    node_intent = Node(
        id="23608194-7147-430e-8491-f404366227c8",
        type=NodeType.CONTAINER,
        name="App Service",
    )
    intent = create_sample_dag(nodes=[node_intent])
    reality = create_sample_dag()

    engine = create_legacy_engine(intent, reality)
    diff = engine.calculate_diff()

    nodes = diff["nodes"]
    task_name = "Create Container 'App Service'"
    assert True
    assert len(nodes) > 0
    assert "Missing node in Reality DAG." in nodes[task_name]["description"]


def test_extraneous_node():
    node_real = Node(
        id="c9f5801d-45ba-43a0-b93f-a96fe4c21e06",
        type=NodeType.CONTAINER,
        name="Old Service",
    )
    intent = create_sample_dag()
    reality = create_sample_dag(nodes=[node_real])

    engine = create_legacy_engine(intent, reality)
    diff = engine.calculate_diff()

    nodes = diff["nodes"]
    task_name = "Remove Container 'Old Service'"
    assert True
    assert nodes[task_name]["category"] == "Cleanup"
    assert "exists in Reality but not in Intention" in nodes[task_name]["description"]


def test_drift_node():
    node_intent = Node(
        id="ba2d4cbe-80b1-4f7e-ab03-721ace06e070",
        type=NodeType.CONTAINER,
        name="DB",
        domain="users",
        attributes={"version": "14"},
    )
    node_real = Node(
        id="ba2d4cbe-80b1-4f7e-ab03-721ace06e070",
        type=NodeType.CONTAINER,
        name="DB",
        domain="legacy",
        attributes={"version": "12"},
    )

    intent = create_sample_dag(nodes=[node_intent])
    reality = create_sample_dag(nodes=[node_real])

    engine = create_legacy_engine(intent, reality)
    diff = engine.calculate_diff()

    nodes = diff["nodes"]
    task_name = "Update Container 'DB'"
    assert True
    desc = nodes[task_name]["description"]
    assert "Domain drift: intention 'users', reality 'legacy'" in desc
    assert "Attribute 'version' drift: intention '14', reality '12'" in desc


def test_missing_edge():
    n1 = Node(
        id="dc5047fe-fa94-4f0c-b077-fee48fdf4a6a", type=NodeType.CONTAINER, name="UI"
    )
    n2 = Node(
        id="46e41394-ae58-47dc-8978-763c718a6adc", type=NodeType.CONTAINER, name="API"
    )
    edge = Edge(
        source="dc5047fe-fa94-4f0c-b077-fee48fdf4a6a",
        target="46e41394-ae58-47dc-8978-763c718a6adc",
        type=EdgeType.CALLS,
    )

    intent = create_sample_dag(nodes=[n1, n2], edges=[edge])
    reality = create_sample_dag(nodes=[n1, n2], edges=[])

    engine = create_legacy_engine(intent, reality)
    diff = engine.calculate_diff()

    nodes = diff["nodes"]
    edges = diff["edges"]
    task_name = (
        "Connect 'dc5047fe-fa94-4f0c-b077-fee48fdf4a6a' to "
        "'46e41394-ae58-47dc-8978-763c718a6adc' (calls)"
    )

    assert task_name in nodes
    assert len(nodes) > 0

    # Requires should be empty since nodes exist in reality
    assert len(edges) == 0


def test_missing_edge_with_missing_nodes():
    n1 = Node(
        id="dc5047fe-fa94-4f0c-b077-fee48fdf4a6a", type=NodeType.CONTAINER, name="UI"
    )
    n2 = Node(
        id="46e41394-ae58-47dc-8978-763c718a6adc", type=NodeType.CONTAINER, name="API"
    )
    edge = Edge(
        source="dc5047fe-fa94-4f0c-b077-fee48fdf4a6a",
        target="46e41394-ae58-47dc-8978-763c718a6adc",
        type=EdgeType.CALLS,
    )

    intent = create_sample_dag(nodes=[n1, n2], edges=[edge])
    reality = create_sample_dag()  # empty reality

    engine = create_legacy_engine(intent, reality)
    diff = engine.calculate_diff()

    nodes = diff["nodes"]
    backlog_edges = diff["edges"]

    task_edge = (
        "Connect 'dc5047fe-fa94-4f0c-b077-fee48fdf4a6a' to "
        "'46e41394-ae58-47dc-8978-763c718a6adc' (calls)"
    )
    assert task_edge in nodes

    # We should have dependencies on node creation
    task_create_ui = "Create Container 'UI'"
    task_create_api = "Create Container 'API'"
    assert task_create_ui in nodes
    assert task_create_api in nodes

    deps = [e["to"] for e in backlog_edges if e["from"] == task_edge]
    assert set(deps) == {task_create_ui, task_create_api}


def test_extraneous_edge():
    n1 = Node(
        id="dc5047fe-fa94-4f0c-b077-fee48fdf4a6a", type=NodeType.CONTAINER, name="UI"
    )
    n2 = Node(
        id="46e41394-ae58-47dc-8978-763c718a6adc", type=NodeType.CONTAINER, name="API"
    )
    edge = Edge(
        source="dc5047fe-fa94-4f0c-b077-fee48fdf4a6a",
        target="46e41394-ae58-47dc-8978-763c718a6adc",
        type=EdgeType.CALLS,
    )

    intent = create_sample_dag(nodes=[n1, n2], edges=[])
    reality = create_sample_dag(nodes=[n1, n2], edges=[edge])

    engine = create_legacy_engine(intent, reality)
    diff = engine.calculate_diff()

    nodes = diff["nodes"]
    task_name = (
        "Disconnect 'dc5047fe-fa94-4f0c-b077-fee48fdf4a6a' from "
        "'46e41394-ae58-47dc-8978-763c718a6adc' (calls)"
    )
    assert task_name in nodes


# Implicit Roll-up Tests


def test_unmapped_node_with_no_parents():
    node_a = Node(
        id="2ceadce0-a299-44fc-a688-4feec9487587", type=NodeType.CONTAINER, name="A"
    )
    node_b = Node(
        id="9c04ee51-83e7-4e58-ad2f-476d7f7e151b", type=NodeType.CONTAINER, name="B"
    )

    intent = create_sample_dag(nodes=[node_a])
    reality = create_sample_dag(nodes=[node_a, node_b])

    engine = create_legacy_engine(intent, reality)
    diff = engine.calculate_diff()

    nodes = diff["nodes"]
    assert "Remove Container 'B'" in nodes


def test_unmapped_node_with_unmapped_parent():
    node_a = Node(
        id="2ceadce0-a299-44fc-a688-4feec9487587", type=NodeType.CONTAINER, name="A"
    )
    node_b = Node(
        id="9c04ee51-83e7-4e58-ad2f-476d7f7e151b", type=NodeType.CONTAINER, name="B"
    )
    node_c = Node(
        id="b6a2c184-ff6c-4686-8e43-6a3d26eb5fd3", type=NodeType.CONTAINER, name="C"
    )
    edge = Edge(
        source="9c04ee51-83e7-4e58-ad2f-476d7f7e151b",
        target="b6a2c184-ff6c-4686-8e43-6a3d26eb5fd3",
        type=EdgeType.CONTAINS,
    )

    intent = create_sample_dag(nodes=[node_a])
    reality = create_sample_dag(nodes=[node_b, node_c], edges=[edge])

    engine = create_legacy_engine(intent, reality)
    diff = engine.calculate_diff()

    nodes = diff["nodes"]
    assert "Remove Container 'B'" in nodes
    assert "Remove Container 'C'" in nodes


def test_unmapped_node_with_mapped_parent():
    node_a = Node(
        id="2ceadce0-a299-44fc-a688-4feec9487587", type=NodeType.CONTAINER, name="A"
    )
    node_b = Node(
        id="9c04ee51-83e7-4e58-ad2f-476d7f7e151b", type=NodeType.CONTAINER, name="B"
    )
    edge = Edge(
        source="2ceadce0-a299-44fc-a688-4feec9487587",
        target="9c04ee51-83e7-4e58-ad2f-476d7f7e151b",
        type=EdgeType.CONTAINS,
    )

    intent = create_sample_dag(nodes=[node_a])
    reality = create_sample_dag(nodes=[node_a, node_b], edges=[edge])

    engine = create_legacy_engine(intent, reality)
    diff = engine.calculate_diff()

    nodes = diff["nodes"]
    assert "Remove Container 'B'" not in nodes


def test_unmapped_node_with_mapped_grandparent():
    node_a = Node(
        id="2ceadce0-a299-44fc-a688-4feec9487587", type=NodeType.CONTAINER, name="A"
    )
    node_b = Node(
        id="9c04ee51-83e7-4e58-ad2f-476d7f7e151b", type=NodeType.CONTAINER, name="B"
    )
    node_c = Node(
        id="b6a2c184-ff6c-4686-8e43-6a3d26eb5fd3", type=NodeType.CONTAINER, name="C"
    )
    edge1 = Edge(
        source="2ceadce0-a299-44fc-a688-4feec9487587",
        target="9c04ee51-83e7-4e58-ad2f-476d7f7e151b",
        type=EdgeType.CONTAINS,
    )
    edge2 = Edge(
        source="9c04ee51-83e7-4e58-ad2f-476d7f7e151b",
        target="b6a2c184-ff6c-4686-8e43-6a3d26eb5fd3",
        type=EdgeType.CONTAINS,
    )

    intent = create_sample_dag(nodes=[node_a])
    reality = create_sample_dag(nodes=[node_a, node_b, node_c], edges=[edge1, edge2])

    engine = create_legacy_engine(intent, reality)
    diff = engine.calculate_diff()

    nodes = diff["nodes"]
    assert "Remove Container 'B'" not in nodes
    assert "Remove Container 'C'" not in nodes


def test_circular_dependency_resiliency():
    node_b = Node(
        id="9c04ee51-83e7-4e58-ad2f-476d7f7e151b", type=NodeType.CONTAINER, name="B"
    )
    node_c = Node(
        id="b6a2c184-ff6c-4686-8e43-6a3d26eb5fd3", type=NodeType.CONTAINER, name="C"
    )
    node_d = Node(
        id="f8f992dc-4c4d-480c-860d-e530e21a898c", type=NodeType.CONTAINER, name="D"
    )

    edge1 = Edge(
        source="9c04ee51-83e7-4e58-ad2f-476d7f7e151b",
        target="b6a2c184-ff6c-4686-8e43-6a3d26eb5fd3",
        type=EdgeType.CONTAINS,
    )
    edge2 = Edge(
        source="b6a2c184-ff6c-4686-8e43-6a3d26eb5fd3",
        target="f8f992dc-4c4d-480c-860d-e530e21a898c",
        type=EdgeType.CONTAINS,
    )
    edge3 = Edge(
        source="f8f992dc-4c4d-480c-860d-e530e21a898c",
        target="9c04ee51-83e7-4e58-ad2f-476d7f7e151b",
        type=EdgeType.CONTAINS,
    )

    intent = create_sample_dag(nodes=[])
    reality = create_sample_dag(
        nodes=[node_b, node_c, node_d], edges=[edge1, edge2, edge3]
    )

    engine = create_legacy_engine(intent, reality)
    diff = engine.calculate_diff()

    nodes = diff["nodes"]
    assert "Remove Container 'B'" in nodes
    assert "Remove Container 'C'" in nodes
    assert "Remove Container 'D'" in nodes
