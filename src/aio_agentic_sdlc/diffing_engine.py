from dataclasses import dataclass
from typing import Any, Dict, List, Literal
from uuid import UUID

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Edge, EdgeType
from aio_agentic_sdlc.reconciliation import ReconciliationEngine


@dataclass(frozen=True)
class DiffPolicy:
    """Select safe reconciliation planning or explicit legacy structural behavior."""

    mode: Literal["safe", "legacy_structural"] = "safe"
    max_tasks: int = 100
    max_candidates: int = 20

    def __post_init__(self):
        if isinstance(self.max_tasks, bool) or not isinstance(self.max_tasks, int):
            raise TypeError("max_tasks must be an integer")
        if self.max_tasks < 1:
            raise ValueError("max_tasks must be at least 1")
        if isinstance(self.max_candidates, bool) or not isinstance(
            self.max_candidates, int
        ):
            raise TypeError("max_candidates must be an integer")
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be at least 1")

    @classmethod
    def safe(
        cls,
        *,
        max_tasks: int = 100,
        max_candidates: int = 20,
    ) -> "DiffPolicy":
        return cls(
            mode="safe",
            max_tasks=max_tasks,
            max_candidates=max_candidates,
        )

    @classmethod
    def legacy_structural(cls) -> "DiffPolicy":
        return cls(mode="legacy_structural")


# aio-sdlc-mapping-approval: {"approved_at":"2026-08-13T19:29:14.286017-04:00","approved_by":"Felix","candidate_reality_id":"6199cd62-9332-5ad1-b458-18bd2e865da1","evidence_digest":"49c7ce1f1cf9501958cbb0a20b0919911d5d9270f20b46b52b7a35535a7eaaf8","intent_id":"fa35fa8a-b6b5-40ca-9080-b31421117e37","rationale":"Approved the DiffingEngine source identity; DAG diff responsibility, documentation, public API, and related-test references match.","schema_version":1,"source_path":"src/aio_agentic_sdlc/diffing_engine.py","source_sha256":"813cc0a840b1c380e98ab6b1fa0b64a060bfc3bba05682b2165cf954f54cee94","symbol_kind":"class","symbol_name":"DiffingEngine"}
# aio-sdlc-node: fa35fa8a-b6b5-40ca-9080-b31421117e37
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
        reality_node = self.reality.nodes[record["reality_candidates"][0]["id"]]
        drift = []
        if (
            intent_node.domain is not None
            and reality_node.domain is not None
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
            f"'{intent_node.name}' [{intent_node.id}]"
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
        canonical_id = intent["id"]
        candidates = [node["id"] for node in record["reality_candidates"]]

        if record["classification"] == "candidate":
            name = f"Review mapping for {node_label} [{canonical_id}]"
            action = "review_mapping"
            description = (
                f"Canonical intent {intent['id']} has one deterministic structural "
                "candidate. Confirm or reject the mapping; do not create or delete "
                "code from this evidence alone."
            )
        elif record["classification"] == "ambiguous":
            name = f"Resolve ambiguous mapping for {node_label} [{canonical_id}]"
            action = "resolve_ambiguous_mapping"
            description = (
                f"Canonical intent {intent['id']} matches multiple observed nodes. "
                "Select no mapping or exactly one mapping using additional evidence."
            )
        else:
            name = f"Investigate implementation for {node_label} [{canonical_id}]"
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
                    "candidate_limit": record["candidate_limit"],
                    "signals": record["evidence"],
                },
            }
        )
        return name, task

    def _calculate_safe(self) -> Dict[str, Any]:
        engine = ReconciliationEngine(self.intention, self.reality)
        classification_order = ("confirmed", "candidate", "ambiguous", "unmapped")
        retained_by_classification = {
            classification: [] for classification in classification_order
        }
        summary = {
            "intention_nodes": len(self.intention.nodes),
            "reality_nodes": len(self.reality.nodes),
            "confirmed": 0,
            "candidate": 0,
            "ambiguous": 0,
            "unmapped": 0,
            "unclassified_reality": 0,
        }
        confirmed_ids = set()
        total_tasks = 0
        for record in engine.iter_intent_records(
            max_candidates=self.policy.max_candidates
        ):
            classification = record["classification"]
            summary[classification] += 1
            task_entry = None
            if record["classification"] == "confirmed":
                confirmed_ids.add(str(UUID(record["intent"]["id"])))
                drift_task = self._confirmed_drift_task(record)
                if drift_task:
                    task_entry = drift_task
            else:
                task_entry = self._review_task(record)
            if task_entry:
                total_tasks += 1
                bucket = retained_by_classification[classification]
                if len(bucket) < self.policy.max_tasks:
                    bucket.append(task_entry)

        summary["unclassified_reality"] = len(self.reality.nodes) - summary["confirmed"]
        returned = []
        for classification in classification_order:
            remaining = self.policy.max_tasks - len(returned)
            if remaining == 0:
                break
            returned.extend(retained_by_classification[classification][:remaining])

        reality_edges = {
            (str(UUID(edge.source)), str(UUID(edge.target)), edge.type)
            for edge in self.reality.edges
        }
        intention_edges = {
            (str(UUID(edge.source)), str(UUID(edge.target)), edge.type): edge
            for edge in self.intention.edges
        }
        for edge_key in sorted(
            intention_edges,
            key=lambda key: (key[0], key[1], key[2].value),
        ):
            edge = intention_edges[edge_key]
            if (
                edge_key[0] in confirmed_ids
                and edge_key[1] in confirmed_ids
                and edge_key not in reality_edges
            ):
                name = (
                    f"Connect confirmed nodes '{edge_key[0]}' to '{edge_key[1]}' "
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
                            "confirmed_endpoint_ids": [edge_key[0], edge_key[1]],
                            "relationship": {
                                "source_id": edge_key[0],
                                "target_id": edge_key[1],
                                "type": edge.type.value,
                            },
                        },
                    }
                )
                total_tasks += 1
                if len(returned) < self.policy.max_tasks:
                    returned.append((name, task))

        nodes = {}
        for name, task in returned:
            if name in nodes:
                raise ValueError(f"Safe reconciliation task key collision: {name}")
            nodes[name] = task
        return {
            "nodes": nodes,
            "edges": [],
            "meta": {
                "mode": "safe",
                "max_tasks": self.policy.max_tasks,
                "max_candidates": self.policy.max_candidates,
                "total_tasks": total_tasks,
                "returned_tasks": len(returned),
                "truncated": len(returned) < total_tasks,
                "reconciliation": summary,
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
