import pytest
from pydantic import ValidationError

from aio_agentic_sdlc.dag_models import Edge, EdgeType, Node, NodeType


def test_node_id_strict_uuid():
    # Valid UUID should pass
    Node(id="123e4567-e89b-12d3-a456-426614174000", type=NodeType.MODULE, name="Test")

    # Invalid ID should fail
    with pytest.raises(ValidationError):
        Node(id="not-a-uuid", type=NodeType.MODULE, name="Test")

    with pytest.raises(ValidationError):
        Node(
            id="123e4567-e89b-12d3-a456-42661417400G", type=NodeType.MODULE, name="Test"
        )


def test_edge_source_target_strict_uuid():
    Edge(
        source="123e4567-e89b-12d3-a456-426614174000",
        target="123e4567-e89b-12d3-a456-426614174001",
        type=EdgeType.CONTAINS,
    )

    with pytest.raises(ValidationError):
        Edge(
            source="invalid-uuid",
            target="123e4567-e89b-12d3-a456-426614174001",
            type=EdgeType.CONTAINS,
        )
