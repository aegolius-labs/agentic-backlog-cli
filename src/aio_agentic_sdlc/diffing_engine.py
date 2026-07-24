from typing import Any, Dict, List

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Edge, EdgeType


class DiffingEngine:
    """
    Computes the difference between an Intention DAG and a Reality DAG,
    generating a backlog of tasks required to reconcile Reality with Intention.
    """

    def __init__(self, intention: DAGManager, reality: DAGManager):
        self.intention = intention
        self.reality = reality

    def _is_implementation_detail(self, node_id: str) -> bool:
        visited = set()

        def check_ancestors(current_id: str) -> bool:
            if current_id in visited:
                return False
            visited.add(current_id)

            # Find all parent nodes in the Reality DAG
            parents = [
                e.source
                for e in self.reality.edges
                if e.target == current_id and e.type == EdgeType.CONTAINS
            ]

            for parent_id in parents:
                if parent_id in self.intention.nodes:
                    return True
                if check_ancestors(parent_id):
                    return True

            return False

        return check_ancestors(node_id)

    def calculate_diff(self) -> Dict[str, Any]:
        """
        Calculates the diff between Intention DAG and Reality DAG.
        Returns a dictionary representing Backlog items.
        """
        backlog_nodes = {}
        backlog_edges = []

        # 1. Missing Nodes (Intention -> Reality)
        for node_id, intent_node in self.intention.nodes.items():
            if node_id not in self.reality.nodes:
                task_name = (
                    f"Create {intent_node.type.value.capitalize()} '{intent_node.name}'"
                )
                backlog_nodes[task_name] = {
                    "item_type": "Task",
                    "impact": 3,
                    "effort": 3,
                    "category": "Architecture",
                    "description": f"Node ID: {node_id}\nMissing node in Reality DAG.",
                    "status": "New",
                    "blockers": [],
                    "scores": {},
                }
            else:
                # Node exists in both, check for drift
                reality_node = self.reality.nodes[node_id]
                drift = []
                if intent_node.domain != reality_node.domain:
                    drift.append(
                        f"Domain drift: intention '{intent_node.domain}', reality '{reality_node.domain}'"
                    )

                # Check attributes if they differ
                intent_attrs = intent_node.attributes or {}
                reality_attrs = reality_node.attributes or {}
                for k, v in intent_attrs.items():
                    if reality_attrs.get(k) != v:
                        drift.append(
                            f"Attribute '{k}' drift: intention '{v}', reality '{reality_attrs.get(k)}'"
                        )

                if drift:
                    task_name = f"Update {intent_node.type.value.capitalize()} '{intent_node.name}'"
                    drift_desc = "\n".join(drift)
                    backlog_nodes[task_name] = {
                        "item_type": "Task",
                        "impact": 2,
                        "effort": 2,
                        "category": "Maintenance",
                        "description": f"Node ID: {node_id}\nDrift detected:\n{drift_desc}",
                        "status": "New",
                        "blockers": [],
                        "scores": {},
                    }

        # 2. Extraneous Nodes (Reality -> Intention)
        for node_id, reality_node in self.reality.nodes.items():
            if node_id not in self.intention.nodes:
                # Implicit Roll-up Check
                if self._is_implementation_detail(node_id):
                    continue

                task_name = f"Remove {reality_node.type.value.capitalize()} '{reality_node.name}'"
                backlog_nodes[task_name] = {
                    "item_type": "Task",
                    "impact": 1,
                    "effort": 2,
                    "category": "Cleanup",
                    "description": f"Node ID: {node_id}\nNode exists in Reality but not in Intention.",
                    "status": "New",
                    "blockers": [],
                    "scores": {},
                }

        # 3. Missing Edges (Intention -> Reality)
        def edge_exists(target_edge: Edge, edges_list: List[Edge]):
            return any(
                e.source == target_edge.source
                and e.target == target_edge.target
                and e.type == target_edge.type
                for e in edges_list
            )

        for intent_edge in self.intention.edges:
            if not edge_exists(intent_edge, self.reality.edges):
                task_name = f"Connect '{intent_edge.source}' to '{intent_edge.target}' ({intent_edge.type.value})"

                requires = []
                if intent_edge.source not in self.reality.nodes:
                    source_node = self.intention.get_node(intent_edge.source)
                    requires.append(
                        f"Create {source_node.type.value.capitalize()} '{source_node.name}'"
                    )

                if intent_edge.target not in self.reality.nodes:
                    target_node = self.intention.get_node(intent_edge.target)
                    requires.append(
                        f"Create {target_node.type.value.capitalize()} '{target_node.name}'"
                    )

                backlog_nodes[task_name] = {
                    "item_type": "Task",
                    "impact": 3,
                    "effort": 2,
                    "category": "Integration",
                    "description": f"Missing edge {intent_edge.type.value} from {intent_edge.source} to {intent_edge.target}.",
                    "status": "New",
                    "blockers": [],
                    "scores": {},
                }

                for req in requires:
                    backlog_edges.append(
                        {"from": task_name, "to": req, "relation": "requires"}
                    )

        # 4. Extraneous Edges (Reality -> Intention)
        for reality_edge in self.reality.edges:
            if not edge_exists(reality_edge, self.intention.edges):
                task_name = f"Disconnect '{reality_edge.source}' from '{reality_edge.target}' ({reality_edge.type.value})"
                backlog_nodes[task_name] = {
                    "item_type": "Task",
                    "impact": 1,
                    "effort": 2,
                    "category": "Cleanup",
                    "description": f"Extraneous edge {reality_edge.type.value} from {reality_edge.source} to {reality_edge.target} found in Reality.",
                    "status": "New",
                    "blockers": [],
                    "scores": {},
                }

        return {"nodes": backlog_nodes, "edges": backlog_edges}
