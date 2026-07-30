from dataclasses import dataclass
from typing import Any, Dict, List, Literal

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Edge, EdgeType
from aio_agentic_sdlc.reconciliation import ReconciliationEngine


@dataclass(frozen=True)
class DiffPolicy:
    """Select safe reconciliation planning or explicit legacy structural behavior."""

    mode: Literal["safe", "legacy_structural"] = "safe"
    max_tasks: int = 100

    def __post_init__(self):
        if isinstance(self.max_tasks, bool) or not isinstance(self.max_tasks, int):
            raise TypeError("max_tasks must be an integer")
        if self.max_tasks < 1:
            raise ValueError("max_tasks must be at least 1")

    @classmethod
    def safe(cls, *, max_tasks: int = 100) -> "DiffPolicy":
        return cls(mode="safe", max_tasks=max_tasks)

    @classmethod
    def legacy_structural(cls) -> "DiffPolicy":
        return cls(mode="legacy_structural")


class DiffingEngine:
    """
    Computes the difference between an Intention DAG and a Reality DAG,
    generating a backlog of tasks required to reconcile Reality with Intention.
    """

    def __init__(
        self,
        intention: DAGManager,
        reality: DAGManager,
        *,
        policy: DiffPolicy | None = None,
    ):
        self.intention = intention
        self.reality = reality
        self.policy = policy or DiffPolicy.safe()

    def calculate_diff(self) -> Dict[str, Any]:
        """Calculate a bounded safe plan unless legacy behavior is explicit."""

        if self.policy.mode == "legacy_structural":
            return self._calculate_legacy_structural()
        return self._calculate_safe()

    @staticmethod
    def _base_task(description: str) -> Dict[str, Any]:
        return {
            "item_type": "Task",
            "impact": 3,
            "effort": 2,
            "category": "Reconciliation",
            "description": description,
            "status": "New",
            "blockers": [],
            "scores": {},
        }

    def _confirmed_drift_task(self, record: Dict[str, Any]):
        intent_node = self.intention.nodes[record["intent"]["id"]]
        reality_node = self.reality.nodes[intent_node.id]
        drift = []
        if (
            reality_node.domain is not None
            and intent_node.domain != reality_node.domain
        ):
            drift.append(
                f"Domain drift: intention '{intent_node.domain}', "
                f"reality '{reality_node.domain}'"
            )
        for key, value in (intent_node.attributes or {}).items():
            reality_attributes = reality_node.attributes or {}
            if key not in reality_attributes:
                continue
            reality_value = reality_attributes[key]
            if reality_value != value:
                drift.append(
                    f"Attribute '{key}' drift: intention '{value}', "
                    f"reality '{reality_value}'"
                )
        if not drift:
            return None

        name = (
            f"Update confirmed {intent_node.type.value.capitalize()} "
            f"'{intent_node.name}' [{intent_node.id[:8]}]"
        )
        task = self._base_task(
            f"Node ID: {intent_node.id}\nConfirmed by canonical GUID.\n"
            + "\n".join(drift)
        )
        task.update(
            {
                "category": "Maintenance",
                "impact": 2,
                "action": "update_confirmed",
                "evidence": {"canonical_guid": intent_node.id},
            }
        )
        return name, task

    def _review_task(self, record: Dict[str, Any]):
        intent = record["intent"]
        node_label = f"{intent['type'].capitalize()} '{intent['name']}'"
        short_id = intent["id"][:8]
        candidates = [node["id"] for node in record["reality_candidates"]]

        if record["classification"] == "candidate":
            name = f"Review mapping for {node_label} [{short_id}]"
            action = "review_mapping"
            description = (
                f"Canonical intent {intent['id']} has one deterministic structural "
                "candidate. Confirm or reject the mapping; do not create or delete "
                "code from this evidence alone."
            )
        elif record["classification"] == "ambiguous":
            name = f"Resolve ambiguous mapping for {node_label} [{short_id}]"
            action = "resolve_ambiguous_mapping"
            description = (
                f"Canonical intent {intent['id']} matches multiple observed nodes. "
                "Select no mapping or exactly one mapping using additional evidence."
            )
        else:
            name = f"Investigate implementation for {node_label} [{short_id}]"
            action = "investigate_intent"
            description = (
                f"Canonical intent {intent['id']} has no deterministic structural "
                "match. Establish implementation evidence before proposing creation."
            )

        task = self._base_task(description)
        task.update(
            {
                "action": action,
                "canonical_intent_id": intent["id"],
                "evidence": {
                    "classification": record["classification"],
                    "candidate_reality_ids": candidates,
                    "signals": record["evidence"],
                },
            }
        )
        return name, task

    def _calculate_safe(self) -> Dict[str, Any]:
        report = ReconciliationEngine(self.intention, self.reality).analyze(
            max_items=max(1, len(self.intention.nodes))
        )
        tasks = []
        for record in report["items"]:
            if record["subject_kind"] != "intent":
                continue
            if record["classification"] == "confirmed":
                drift_task = self._confirmed_drift_task(record)
                if drift_task:
                    tasks.append(drift_task)
            else:
                tasks.append(self._review_task(record))

        confirmed_ids = {
            record["intent"]["id"]
            for record in report["items"]
            if record["subject_kind"] == "intent"
            and record["classification"] == "confirmed"
        }
        reality_edges = {
            (edge.source, edge.target, edge.type) for edge in self.reality.edges
        }
        for edge in self.intention.edges:
            edge_key = (edge.source, edge.target, edge.type)
            if (
                edge.source in confirmed_ids
                and edge.target in confirmed_ids
                and edge_key not in reality_edges
            ):
                name = (
                    f"Connect confirmed nodes '{edge.source}' to '{edge.target}' "
                    f"({edge.type.value})"
                )
                task = self._base_task(
                    f"Both endpoints are confirmed by canonical GUID; the "
                    f"{edge.type.value} edge is absent from Reality."
                )
                task.update(
                    {
                        "action": "connect_confirmed",
                        "evidence": {
                            "confirmed_endpoint_ids": [edge.source, edge.target]
                        },
                    }
                )
                tasks.append((name, task))

        total_tasks = len(tasks)
        returned = tasks[: self.policy.max_tasks]
        nodes = {name: task for name, task in returned}
        return {
            "nodes": nodes,
            "edges": [],
            "meta": {
                "mode": "safe",
                "max_tasks": self.policy.max_tasks,
                "total_tasks": total_tasks,
                "returned_tasks": len(returned),
                "truncated": len(returned) < total_tasks,
                "reconciliation": report["summary"],
            },
        }

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

    def _calculate_legacy_structural(self) -> Dict[str, Any]:
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
