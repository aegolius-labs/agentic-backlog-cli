import os
import tempfile
from typing import Dict, List

import yaml

from aio_agentic_sdlc.dag_models import Edge, EdgeType, Metadata, Node


class DAGValidationError(ValueError):
    """Raised for an expected invalid DAG structure or operation."""


class DAGNotFoundError(FileNotFoundError):
    """Raised when a requested DAG artifact does not exist."""


class DAGManager:
    def __init__(self, metadata: Metadata, nodes: List[Node], edges: List[Edge]):
        self.metadata = metadata
        raw_nodes = list(nodes)
        seen_ids: set[str] = set()
        for node in raw_nodes:
            if node.id in seen_ids:
                raise DAGValidationError(f"Duplicate node ID {node.id}.")
            seen_ids.add(node.id)
        self.nodes: Dict[str, Node] = {n.id: n for n in raw_nodes}
        self.edges: List[Edge] = edges

    @classmethod
    def load(cls, filepath: str) -> "DAGManager":
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except FileNotFoundError as error:
            raise DAGNotFoundError(f"DAG file does not exist: {filepath}") from error

        metadata = Metadata(**data.get("metadata", {}))
        nodes = [Node(**n) for n in data.get("nodes", [])]
        edges = [Edge(**e) for e in data.get("edges", [])]

        return cls(metadata, nodes, edges)

    def save(self, filepath: str):
        data = {
            "metadata": self.metadata.model_dump(mode="json", exclude_none=True),
            "nodes": [
                n.model_dump(mode="json", exclude_none=True)
                for n in self.nodes.values()
            ],
            "edges": [e.model_dump(mode="json", exclude_none=True) for e in self.edges],
        }
        target = os.path.abspath(filepath)
        target_dir = os.path.dirname(target) or "."
        os.makedirs(target_dir, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            dir=target_dir,
            prefix=f".{os.path.basename(target)}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                yaml.dump(data, f, sort_keys=False, default_flow_style=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, target)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def validate(self):
        # Reference Integrity
        for edge in self.edges:
            if edge.source not in self.nodes:
                raise DAGValidationError(
                    f"Edge source node {edge.source} does not exist."
                )
            if edge.target not in self.nodes:
                raise DAGValidationError(
                    f"Edge target node {edge.target} does not exist."
                )

        # Cycle detection for specific edge types
        graph = {n_id: [] for n_id in self.nodes}
        for edge in self.edges:
            if edge.type in [EdgeType.DEPENDS_ON, EdgeType.CALLS, EdgeType.CONTAINS]:
                graph[edge.source].append(edge.target)

        visited = set()
        rec_stack = set()

        def dfs(node_id):
            visited.add(node_id)
            rec_stack.add(node_id)

            for neighbor in graph.get(node_id, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node_id)
            return False

        for node_id in self.nodes:
            if node_id not in visited:
                if dfs(node_id):
                    raise DAGValidationError(
                        f"Cycle detected involving node {node_id}."
                    )

    def validate_intent_ir(self, require_all: bool = True):
        """Validate Intent IR coverage in addition to the base DAG constraints."""
        self.validate()
        if require_all:
            missing = [
                node_id for node_id, node in self.nodes.items() if node.intent is None
            ]
            if missing:
                raise DAGValidationError(
                    "Intent IR is missing for node(s): " + ", ".join(sorted(missing))
                )

    def render_intent_summary(self, node_id: str = None) -> str:
        """Render an auditable Intent IR review without exposing raw DAG YAML."""
        if node_id is not None:
            nodes = [self.get_node(node_id)]
        else:
            nodes = list(self.nodes.values())

        nodes = [node for node in nodes if node.intent is not None]
        if not nodes:
            return "No nodes contain Intent IR."

        lines = [f"Intent review: {self.metadata.name}"]
        for node in nodes:
            intent = node.intent
            lines.extend(
                [
                    "",
                    f"## {node.name} ({node.id})",
                    f"Confidence: {intent.confidence:.2f}",
                    f"Approval: {intent.approval.state.value}",
                    f"Responsible agent: {intent.responsible_agent}",
                    f"Generator: {intent.generator_version}",
                    "Provenance:",
                ]
            )
            for source in intent.provenance:
                lines.append(
                    f"- [{source.source_type.value}] {source.reference}: {source.statement}"
                )

            lines.append("Acceptance criteria:")
            for criterion in intent.acceptance_criteria:
                lines.append(f"- {criterion.id}: {criterion.statement}")
                for evidence in criterion.required_evidence:
                    lines.append(f"  - Required evidence: {evidence}")

            lines.append("Assumptions:")
            lines.extend(f"- {assumption}" for assumption in intent.assumptions)
            if not intent.assumptions:
                lines.append("- None")

            lines.append("Ambiguities:")
            for ambiguity in intent.ambiguities:
                resolution = (
                    f"; resolution: {ambiguity.resolution}"
                    if ambiguity.resolution
                    else ""
                )
                lines.append(
                    f"- [{ambiguity.status.value}] {ambiguity.question}{resolution}"
                )
            if not intent.ambiguities:
                lines.append("- None")

            lines.append("Revision history:")
            for revision in intent.revision_history:
                lines.append(
                    f"- r{revision.revision} {revision.recorded_at.isoformat()} "
                    f"by {revision.actor}: {revision.summary}"
                )

        return "\n".join(lines)

    def add_node(self, node: Node):
        if node.id in self.nodes:
            raise DAGValidationError(f"Node {node.id} already exists.")
        self.nodes[node.id] = node

    def update_node(self, node_id: str, **kwargs):
        if node_id not in self.nodes:
            raise DAGValidationError(f"Node {node_id} does not exist.")

        node = self.nodes[node_id]
        update_data = {k: v for k, v in kwargs.items() if v is not None}
        updated_node = Node.model_validate({**node.model_dump(), **update_data})
        self.nodes[node_id] = updated_node

    def remove_node(self, node_id: str):
        if node_id not in self.nodes:
            raise DAGValidationError(f"Node {node_id} does not exist.")

        del self.nodes[node_id]

        # Cascade remove edges
        self.edges = [
            e for e in self.edges if e.source != node_id and e.target != node_id
        ]

    def get_node(self, node_id: str) -> Node:
        if node_id not in self.nodes:
            raise DAGValidationError(f"Node {node_id} does not exist.")
        return self.nodes[node_id]

    def find_nodes(self, **filters) -> List[Node]:
        result = []
        for node in self.nodes.values():
            match = True
            for k, v in filters.items():
                if v is None:
                    continue
                if getattr(node, k, None) != v:
                    match = False
                    break
            if match:
                result.append(node)
        return result

    def add_edge(self, edge: Edge):
        if edge.source not in self.nodes:
            raise DAGValidationError(f"Source node {edge.source} does not exist.")
        if edge.target not in self.nodes:
            raise DAGValidationError(f"Target node {edge.target} does not exist.")

        self.edges.append(edge)

        try:
            self.validate()
        except DAGValidationError as e:
            # Revert if adding creates an invalid DAG
            self.edges.pop()
            raise e

    def remove_edge(self, source: str, target: str, edge_type: EdgeType):
        initial_len = len(self.edges)
        self.edges = [
            e
            for e in self.edges
            if not (e.source == source and e.target == target and e.type == edge_type)
        ]
        if len(self.edges) == initial_len:
            raise DAGValidationError(
                f"Edge {source} -> {target} ({edge_type}) does not exist."
            )

    def get_edges(
        self, source: str = None, target: str = None, edge_type: EdgeType = None
    ) -> List[Edge]:
        result = []
        for edge in self.edges:
            if source and edge.source != source:
                continue
            if target and edge.target != target:
                continue
            if edge_type and edge.type != edge_type:
                continue
            result.append(edge)
        return result
