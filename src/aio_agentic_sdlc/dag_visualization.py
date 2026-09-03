# aio-sdlc-node: 841ddc3e-b7a2-57d3-80f1-bfb5ef9c6f58
"""Read-only, deterministic DAG visualization and comparison reports."""

from __future__ import annotations

import html
import json
import re
from collections import deque
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Edge, Node
from aio_agentic_sdlc.reality_dag_generator import RealityDAGGenerator
from aio_agentic_sdlc.reconciliation import ReconciliationEngine, normalize_node_name
from aio_agentic_sdlc.source_locations import SourceLocation
from aio_agentic_sdlc.workspace import INTENTION_DAG_FILE, REALITY_DAG_FILE

REPORT_SCHEMA_VERSION = 1
DEFAULT_MAX_ITEMS = 100
DEFAULT_MAX_EDGES = 200
DEFAULT_MAX_CANDIDATES = 20
MAX_REPORT_TEXT = 200
MAX_MERMAID_LABEL = 120
SUPPORTED_VIEWS = {"intention", "reality", "comparison"}
CLASSIFICATIONS = ("confirmed", "candidate", "ambiguous", "unmapped")


class DAGVisualizationError(ValueError):
    """Raised for an expected invalid visualization request or DAG identity."""


def _canonical_guid(value: str) -> str:
    return str(UUID(value))


def _validate_integer(value: int, *, name: str, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < minimum:
        raise DAGVisualizationError(f"{name} must be at least {minimum}")


def _bounded_text(value: Any, limit: int = MAX_REPORT_TEXT) -> tuple[str, bool]:
    text = str(value)
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _bounded_value(value: Any) -> Any:
    """Bound strings in small, engine-owned reconciliation evidence structures."""

    if isinstance(value, str):
        return _bounded_text(value)[0]
    if isinstance(value, dict):
        return {str(key): _bounded_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_bounded_value(item) for item in value]
    return value


def _normalize_dag(manager: DAGManager, *, dag_name: str) -> DAGManager:
    """Return a canonical-GUID copy without changing the supplied manager."""

    canonical_sources: dict[str, str] = {}
    nodes: list[Node] = []
    for source_id, node in manager.nodes.items():
        canonical_id = _canonical_guid(source_id)
        if canonical_id in canonical_sources:
            raise DAGVisualizationError(
                f"{dag_name} contains duplicate canonical GUID {canonical_id}: "
                f"{canonical_sources[canonical_id]} and {source_id}"
            )
        canonical_sources[canonical_id] = source_id
        nodes.append(node.model_copy(update={"id": canonical_id}))

    edges = [
        edge.model_copy(
            update={
                "source": _canonical_guid(edge.source),
                "target": _canonical_guid(edge.target),
            }
        )
        for edge in manager.edges
    ]
    normalized = DAGManager(manager.metadata.model_copy(), nodes, edges)
    normalized.validate()
    return normalized


def _node_report(node: Node) -> dict[str, Any]:
    name, name_truncated = _bounded_text(node.name)
    report: dict[str, Any] = {
        "id": _canonical_guid(node.id),
        "type": node.type.value,
        "name": name,
        "name_truncated": name_truncated,
    }
    if node.domain is not None:
        domain, domain_truncated = _bounded_text(node.domain)
        report.update({"domain": domain, "domain_truncated": domain_truncated})
    if node.description is not None:
        description, description_truncated = _bounded_text(node.description)
        report.update(
            {
                "description": description,
                "description_truncated": description_truncated,
            }
        )
    return report


def _edge_sort_key(edge: Edge) -> tuple[str, str, str, str]:
    return (
        _canonical_guid(edge.source),
        _canonical_guid(edge.target),
        edge.type.value,
        edge.description or "",
    )


def _edge_report(edge: Edge) -> dict[str, Any]:
    report: dict[str, Any] = {
        "source_id": _canonical_guid(edge.source),
        "target_id": _canonical_guid(edge.target),
        "type": edge.type.value,
    }
    if edge.description is not None:
        description, description_truncated = _bounded_text(edge.description)
        report.update(
            {
                "description": description,
                "description_truncated": description_truncated,
            }
        )
    return report


def _dag_signature(manager: DAGManager) -> str:
    """Return a stable exact signature for one already-normalized DAG."""

    nodes = [
        manager.nodes[node_id].model_dump(mode="json", exclude_none=True)
        for node_id in sorted(manager.nodes)
    ]
    edges = [
        edge.model_dump(mode="json", exclude_none=True)
        for edge in sorted(manager.edges, key=_edge_sort_key)
    ]
    payload = {
        "metadata": manager.metadata.model_dump(mode="json", exclude_none=True),
        "nodes": nodes,
        "edges": edges,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _collection_limit(
    *, name: str, maximum: int, total: int, returned: int
) -> dict[str, Any]:
    return {
        name: maximum,
        "total_items" if name == "max_items" else "total_edges": total,
        "returned_items" if name == "max_items" else "returned_edges": returned,
        "truncated": returned < total,
    }


class DAGVisualizationEngine:
    """Build one bounded report from validated canonical DAG snapshots."""

    def __init__(
        self,
        intention: DAGManager,
        reality: DAGManager,
        *,
        source_locations: (
            Mapping[str, Iterable[SourceLocation | Mapping[str, Any]]] | None
        ) = None,
        source_discovery: Mapping[str, str] | None = None,
    ):
        self.intention = _normalize_dag(intention, dag_name="Intention DAG")
        self.reality = _normalize_dag(reality, dag_name="Reality DAG")
        self.source_locations = self._normalize_source_locations(source_locations or {})
        self.source_discovery = dict(
            source_discovery
            or (
                {
                    "state": "available",
                    "reason": "Exact SourceLocation evidence was supplied.",
                }
                if self.source_locations
                else {
                    "state": "unavailable",
                    "reason": "No exact SourceLocation evidence was supplied.",
                }
            )
        )
        self.reconciliation = ReconciliationEngine(self.intention, self.reality)

    @classmethod
    def from_project(cls, project_path: str | Path) -> "DAGVisualizationEngine":
        """Load canonical state and admit fresh source locations only on exact match."""

        project_root = Path(project_path).resolve()
        intention = DAGManager.load(str(project_root / INTENTION_DAG_FILE))
        reality = DAGManager.load(str(project_root / REALITY_DAG_FILE))
        engine = cls(intention, reality)

        try:
            generator = RealityDAGGenerator(
                root_dir=str(project_root),
                system_name=reality.metadata.name,
            )
            generated_reality = _normalize_dag(
                generator.generate(),
                dag_name="Fresh Reality DAG",
            )
            if _dag_signature(generated_reality) != _dag_signature(engine.reality):
                engine.source_discovery = {
                    "state": "unavailable",
                    "reason": (
                        "Fresh generated Reality does not match the loaded canonical "
                        "Reality DAG."
                    ),
                }
                return engine
            engine.source_locations = engine._normalize_source_locations(
                generator.source_locations
            )
            engine.source_discovery = {
                "state": "available",
                "reason": (
                    "Fresh generated Reality exactly matches the loaded canonical "
                    "Reality DAG."
                ),
            }
        except Exception as exc:
            detail = _bounded_text(str(exc), limit=120)[0]
            engine.source_locations = {}
            engine.source_discovery = {
                "state": "unavailable",
                "reason": f"Fresh source discovery failed: {detail}",
            }
        return engine

    @staticmethod
    def _normalize_source_locations(
        locations: Mapping[str, Iterable[SourceLocation | Mapping[str, Any]]],
    ) -> dict[str, list[SourceLocation]]:
        normalized: dict[str, list[SourceLocation]] = {}
        for source_id, values in locations.items():
            canonical_id = _canonical_guid(source_id)
            retained = normalized.setdefault(canonical_id, [])
            for value in values:
                location = (
                    value
                    if isinstance(value, SourceLocation)
                    else SourceLocation(**dict(value))
                )
                if location not in retained:
                    retained.append(location)
        for values in normalized.values():
            values.sort(
                key=lambda location: (
                    location.path,
                    location.definition_line,
                    location.marker_line,
                    location.symbol_kind,
                    location.symbol_name,
                    location.source_sha256,
                )
            )
        return normalized

    @staticmethod
    def _distances(
        manager: DAGManager,
        focus_node_id: str | None,
        depth: int,
    ) -> dict[str, int]:
        if focus_node_id is None:
            return {node_id: 0 for node_id in manager.nodes}
        if focus_node_id not in manager.nodes:
            return {}

        adjacency = {node_id: set() for node_id in manager.nodes}
        for edge in manager.edges:
            adjacency[edge.source].add(edge.target)
            adjacency[edge.target].add(edge.source)

        distances = {focus_node_id: 0}
        pending = deque([focus_node_id])
        while pending:
            current = pending.popleft()
            current_distance = distances[current]
            if current_distance == depth:
                continue
            for neighbor in sorted(adjacency[current]):
                if neighbor in distances:
                    continue
                distances[neighbor] = current_distance + 1
                pending.append(neighbor)
        return distances

    @staticmethod
    def _seeded_distances(
        manager: DAGManager,
        seeds: set[str],
        depth: int,
    ) -> dict[str, int]:
        if not seeds:
            return {}
        adjacency = {node_id: set() for node_id in manager.nodes}
        for edge in manager.edges:
            adjacency[edge.source].add(edge.target)
            adjacency[edge.target].add(edge.source)

        distances = {node_id: 0 for node_id in seeds}
        pending = deque(sorted(seeds))
        while pending:
            current = pending.popleft()
            current_distance = distances[current]
            if current_distance == depth:
                continue
            for neighbor in sorted(adjacency[current]):
                proposed_distance = current_distance + 1
                if neighbor in distances and distances[neighbor] <= proposed_distance:
                    continue
                distances[neighbor] = proposed_distance
                pending.append(neighbor)
        return distances

    def _source_evidence(
        self,
        reality_id: str,
        *,
        max_candidates: int,
    ) -> dict[str, Any]:
        locations = self.source_locations.get(reality_id, [])
        retained = locations[:max_candidates]
        location_reports: list[dict[str, Any]] = []
        location_truncation: list[dict[str, bool]] = []
        for location in retained:
            fields: dict[str, str] = {}
            truncation: dict[str, bool] = {}
            for field in ("path", "symbol_kind", "symbol_name", "source_sha256"):
                fields[field], truncation[field] = _bounded_text(
                    getattr(location, field)
                )
            location_reports.append(
                {
                    "path": fields["path"],
                    "symbol_kind": fields["symbol_kind"],
                    "symbol_name": fields["symbol_name"],
                    "definition_line": location.definition_line,
                    "marker_line": location.marker_line,
                    "source_sha256": fields["source_sha256"],
                }
            )
            location_truncation.append(truncation)
        return {
            "state": "available" if retained else "unavailable",
            "locations": location_reports,
            "location_truncation": location_truncation,
            "limit": _collection_limit(
                name="max_items",
                maximum=max_candidates,
                total=len(locations),
                returned=len(retained),
            ),
            **(
                {}
                if retained
                else {"reason": "No exact SourceLocation evidence was supplied."}
            ),
        }

    @staticmethod
    def _evidence_state(
        *, identity_available: bool, source_available: bool
    ) -> dict[str, str]:
        return {
            "identity": "available" if identity_available else "unavailable",
            "source": "available" if source_available else "unavailable",
            "behavioral_verification": "unavailable",
        }

    def _intention_record(self, node_id: str, *, distance: int) -> dict[str, Any]:
        return {
            "canonical_id": node_id,
            "subject_kind": "intention",
            "distance": distance,
            "intention": _node_report(self.intention.nodes[node_id]),
            "evidence_state": self._evidence_state(
                identity_available=False,
                source_available=False,
            ),
        }

    def _reality_record(
        self,
        node_id: str,
        *,
        distance: int,
        max_candidates: int,
        classification: str | None = None,
    ) -> dict[str, Any]:
        source_evidence = self._source_evidence(
            node_id,
            max_candidates=max_candidates,
        )
        record = {
            "canonical_id": node_id,
            "subject_kind": "reality",
            "distance": distance,
            "reality": _node_report(self.reality.nodes[node_id]),
            "source_evidence": source_evidence,
            "evidence_state": self._evidence_state(
                identity_available=False,
                source_available=source_evidence["state"] == "available",
            ),
        }
        if classification is not None:
            record["classification"] = classification
        return record

    def _comparison_intent_record(
        self,
        reconciliation_record: dict[str, Any],
        *,
        distance: int,
        max_candidates: int,
        preferred_reality_id: str | None = None,
    ) -> dict[str, Any]:
        intent_id = _canonical_guid(reconciliation_record["intent"]["id"])
        reality_candidates: list[dict[str, Any]] = []
        source_available = False
        candidate_summaries = list(reconciliation_record["reality_candidates"])
        if preferred_reality_id is not None and not any(
            _canonical_guid(candidate["id"]) == preferred_reality_id
            for candidate in candidate_summaries
        ):
            preferred = self.reality.nodes[preferred_reality_id]
            preferred_summary = {
                "id": preferred.id,
                "type": preferred.type.value,
                "name": preferred.name,
            }
            if len(candidate_summaries) == max_candidates:
                candidate_summaries[-1] = preferred_summary
            else:
                candidate_summaries.append(preferred_summary)
        candidate_summaries.sort(
            key=lambda candidate: (
                _canonical_guid(candidate["id"]) != preferred_reality_id,
                _canonical_guid(candidate["id"]),
            )
        )
        for candidate in candidate_summaries:
            candidate_id = _canonical_guid(candidate["id"])
            source_evidence = self._source_evidence(
                candidate_id,
                max_candidates=max_candidates,
            )
            source_available = (
                source_available or source_evidence["state"] == "available"
            )
            candidate_report = _node_report(self.reality.nodes[candidate_id])
            candidate_report["source_evidence"] = source_evidence
            reality_candidates.append(candidate_report)
        reality_candidates.sort(key=lambda candidate: candidate["id"])

        total_candidates = reconciliation_record.get("candidate_limit", {}).get(
            "total_candidates", len(reality_candidates)
        )
        candidate_limit = {
            "max_candidates": max_candidates,
            "total_candidates": total_candidates,
            "returned_candidates": len(reality_candidates),
            "truncated": len(reality_candidates) < total_candidates,
        }
        identity_evidence = _bounded_value(reconciliation_record.get("evidence", []))
        return {
            "canonical_id": intent_id,
            "subject_kind": "intent",
            "distance": distance,
            "classification": reconciliation_record["classification"],
            "intention": _node_report(self.intention.nodes[intent_id]),
            "reality_candidates": reality_candidates,
            "candidate_limit": candidate_limit,
            "identity_evidence": identity_evidence,
            "requires_approval": reconciliation_record["requires_approval"],
            "evidence_state": self._evidence_state(
                identity_available=bool(identity_evidence),
                source_available=source_available,
            ),
        }

    @staticmethod
    def _bounded_relationships(
        manager: DAGManager,
        selected_ids: set[str],
        *,
        max_edges: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        total = 0
        retained: list[Edge] = []
        for edge in manager.edges:
            if edge.source not in selected_ids or edge.target not in selected_ids:
                continue
            total += 1
            if len(retained) < max_edges:
                retained.append(edge)
                retained.sort(key=_edge_sort_key)
            elif _edge_sort_key(edge) < _edge_sort_key(retained[-1]):
                retained[-1] = edge
                retained.sort(key=_edge_sort_key)
        return (
            [_edge_report(edge) for edge in retained],
            _collection_limit(
                name="max_edges",
                maximum=max_edges,
                total=total,
                returned=len(retained),
            ),
        )

    def build_report(
        self,
        *,
        view: str = "comparison",
        focus_node_id: str | None = None,
        depth: int = 1,
        max_items: int = DEFAULT_MAX_ITEMS,
        max_edges: int = DEFAULT_MAX_EDGES,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
    ) -> dict[str, Any]:
        """Build one deterministic bounded view without mutating either DAG."""

        if not isinstance(view, str) or view.casefold() not in SUPPORTED_VIEWS:
            raise DAGVisualizationError(f"Unsupported view: {view}")
        view = view.casefold()
        _validate_integer(depth, name="depth", minimum=0)
        _validate_integer(max_items, name="max_items", minimum=1)
        _validate_integer(max_edges, name="max_edges", minimum=1)
        _validate_integer(max_candidates, name="max_candidates", minimum=1)

        focus_id = _canonical_guid(focus_node_id) if focus_node_id is not None else None
        focus_in_intention = focus_id is not None and focus_id in self.intention.nodes
        focus_in_reality = focus_id is not None and focus_id in self.reality.nodes
        focus_is_known = (
            focus_in_intention
            if view == "intention"
            else (
                focus_in_reality
                if view == "reality"
                else focus_in_intention or focus_in_reality
            )
        )
        if focus_id is not None and not focus_is_known:
            raise DAGVisualizationError(
                f"Unknown focus node for {view} view: {focus_id}"
            )

        intention_distances = self._distances(
            self.intention,
            focus_id if focus_in_intention else None,
            depth,
        )
        reality_distances = self._distances(
            self.reality,
            focus_id if focus_in_reality else None,
            depth,
        )
        if focus_id is not None and not focus_in_intention:
            intention_distances = {}
        if focus_id is not None and not focus_in_reality:
            reality_distances = {}

        focused_candidate_intent_ids: set[str] = set()
        if view == "comparison" and focus_in_reality and not focus_in_intention:
            focused_reality = self.reality.nodes[focus_id]
            normalized_focus_name = normalize_node_name(focused_reality.name)
            if normalized_focus_name:
                focused_candidate_intent_ids = {
                    intent_id
                    for intent_id, intent_node in self.intention.nodes.items()
                    if intent_node.type == focused_reality.type
                    and normalize_node_name(intent_node.name) == normalized_focus_name
                }
            intention_distances = self._seeded_distances(
                self.intention,
                focused_candidate_intent_ids,
                depth,
            )

        records: list[dict[str, Any]] = []
        classification_counts = {
            classification: 0 for classification in CLASSIFICATIONS
        }
        if view == "intention":
            ordered = sorted(
                intention_distances.items(),
                key=lambda item: (item[1], item[0]),
            )
            total_records = len(ordered)
            records = [
                self._intention_record(node_id, distance=distance)
                for node_id, distance in ordered[:max_items]
            ]
        elif view == "reality":
            ordered = sorted(
                reality_distances.items(),
                key=lambda item: (item[1], item[0]),
            )
            total_records = len(ordered)
            records = [
                self._reality_record(
                    node_id,
                    distance=distance,
                    max_candidates=max_candidates,
                )
                for node_id, distance in ordered[:max_items]
            ]
        else:
            descriptors: list[
                tuple[tuple[int, str, str], str, dict[str, Any] | str]
            ] = []

            def retain_descriptor(
                sort_key: tuple[int, str, str],
                kind: str,
                payload: dict[str, Any] | str,
            ) -> None:
                descriptor = (sort_key, kind, payload)
                if len(descriptors) < max_items:
                    descriptors.append(descriptor)
                    descriptors.sort(key=lambda item: item[0])
                elif sort_key < descriptors[-1][0]:
                    descriptors[-1] = descriptor
                    descriptors.sort(key=lambda item: item[0])

            confirmed_reality_ids: set[str] = set()
            total_records = 0
            for reconciliation_record in self.reconciliation.iter_intent_records(
                max_candidates=max_candidates
            ):
                intent_id = _canonical_guid(reconciliation_record["intent"]["id"])
                if reconciliation_record["classification"] == "confirmed":
                    confirmed_reality_ids.update(
                        _canonical_guid(candidate["id"])
                        for candidate in reconciliation_record["reality_candidates"]
                    )
                if intent_id not in intention_distances:
                    continue
                classification_counts[reconciliation_record["classification"]] += 1
                total_records += 1
                retain_descriptor(
                    (intention_distances[intent_id], intent_id, "intent"),
                    "intent",
                    reconciliation_record,
                )
            for reality_id, distance in reality_distances.items():
                if reality_id in confirmed_reality_ids:
                    continue
                total_records += 1
                retain_descriptor(
                    (distance, reality_id, "reality"),
                    "reality",
                    reality_id,
                )
            for sort_key, kind, payload in descriptors:
                if kind == "intent":
                    assert isinstance(payload, dict)
                    records.append(
                        self._comparison_intent_record(
                            payload,
                            distance=sort_key[0],
                            max_candidates=max_candidates,
                            preferred_reality_id=(
                                focus_id
                                if payload["intent"]["id"]
                                in focused_candidate_intent_ids
                                else None
                            ),
                        )
                    )
                else:
                    assert isinstance(payload, str)
                    records.append(
                        self._reality_record(
                            payload,
                            distance=sort_key[0],
                            max_candidates=max_candidates,
                            classification="unclassified_reality",
                        )
                    )

        selected_intention_ids = set(intention_distances)
        selected_reality_ids = set(reality_distances)
        if view == "reality":
            intended_relationships: list[dict[str, Any]] = []
            intended_limit = _collection_limit(
                name="max_edges", maximum=max_edges, total=0, returned=0
            )
        else:
            intended_relationships, intended_limit = self._bounded_relationships(
                self.intention,
                selected_intention_ids,
                max_edges=max_edges,
            )
        if view == "intention":
            observed_relationships: list[dict[str, Any]] = []
            observed_limit = _collection_limit(
                name="max_edges", maximum=max_edges, total=0, returned=0
            )
        else:
            observed_relationships, observed_limit = self._bounded_relationships(
                self.reality,
                selected_reality_ids,
                max_edges=max_edges,
            )

        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "view": view,
            "focus": {"node_id": focus_id, "depth": depth},
            "source_discovery": self.source_discovery,
            "summary": {
                "available_intention_nodes": len(self.intention.nodes),
                "available_reality_nodes": len(self.reality.nodes),
                "selected_intention_nodes": len(selected_intention_ids),
                "selected_reality_nodes": len(selected_reality_ids),
                "classifications": classification_counts,
                "intended_relationships": intended_limit["total_edges"],
                "observed_relationships": observed_limit["total_edges"],
            },
            "limits": {
                "records": _collection_limit(
                    name="max_items",
                    maximum=max_items,
                    total=total_records,
                    returned=len(records),
                ),
                "intended_relationships": intended_limit,
                "observed_relationships": observed_limit,
            },
            "records": records,
            "intended_relationships": intended_relationships,
            "observed_relationships": observed_relationships,
        }


def _plain_label(value: Any, *, limit: int = MAX_MERMAID_LABEL) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value))
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def _mermaid_label(value: Any) -> str:
    escaped = html.escape(_plain_label(value), quote=True)
    return escaped.replace("%", "&#37;")


def _record_entities(
    report: Mapping[str, Any],
) -> tuple[
    list[tuple[tuple[str, str], str]],
    list[tuple[tuple[str, str], tuple[str, str], str]],
]:
    entities: dict[tuple[str, str], str] = {}
    identity_edges: list[tuple[tuple[str, str], tuple[str, str], str]] = []
    for record in report.get("records", []):
        if record["subject_kind"] in {"intention", "intent"}:
            node = record["intention"]
            key = ("intention", node["id"])
            suffix = (
                f" — {record['classification']}" if "classification" in record else ""
            )
            entities[key] = f"{node['name']} — intention/{node['type']}{suffix}"
            for candidate in record.get("reality_candidates", []):
                candidate_key = ("reality", candidate["id"])
                entities[candidate_key] = (
                    f"{candidate['name']} — reality/{candidate['type']}"
                )
                identity_edges.append((key, candidate_key, record["classification"]))
        else:
            node = record["reality"]
            key = ("reality", node["id"])
            entities[key] = f"{node['name']} — reality/{node['type']}"
    return sorted(entities.items()), identity_edges


def render_dag_mermaid(report: Mapping[str, Any]) -> str:
    """Render a report as safe Mermaid using only synthetic identifiers."""

    entity_items, identity_edges = _record_entities(report)
    synthetic_ids = {
        key: f"n{index:04d}" for index, (key, _) in enumerate(entity_items)
    }
    lines = ["flowchart LR"]
    for key, label in entity_items:
        lines.append(f'  {synthetic_ids[key]}["{_mermaid_label(label)}"]')

    edges: list[tuple[str, str, str]] = []
    for relationship in report.get("intended_relationships", []):
        source = ("intention", relationship["source_id"])
        target = ("intention", relationship["target_id"])
        if source in synthetic_ids and target in synthetic_ids:
            edges.append(
                (
                    synthetic_ids[source],
                    synthetic_ids[target],
                    f"intended {relationship['type']}",
                )
            )
    for relationship in report.get("observed_relationships", []):
        source = ("reality", relationship["source_id"])
        target = ("reality", relationship["target_id"])
        if source in synthetic_ids and target in synthetic_ids:
            edges.append(
                (
                    synthetic_ids[source],
                    synthetic_ids[target],
                    f"observed {relationship['type']}",
                )
            )
    for source, target, classification in identity_edges:
        if source in synthetic_ids and target in synthetic_ids:
            edges.append(
                (
                    synthetic_ids[source],
                    synthetic_ids[target],
                    f"identity {classification}",
                )
            )
    for source, target, label in sorted(edges):
        lines.append(f'  {source} -->|"{_mermaid_label(label)}"| {target}')
    return "\n".join(lines)


def render_dag_human(report: Mapping[str, Any]) -> str:
    """Render a concise name-first report without exposing DAG serialization."""

    def display_name(node: Mapping[str, Any]) -> str:
        return _plain_label(node.get("name", "Unnamed node"))

    def source_suffix(source_evidence: Mapping[str, Any] | None) -> str:
        locations = (source_evidence or {}).get("locations", [])
        if not locations:
            return "source unavailable"
        rendered_locations = []
        for location in locations:
            path = _plain_label(location.get("path", "unknown path"), limit=160)
            line = _plain_label(location.get("definition_line", "?"), limit=12)
            rendered_locations.append(f"{path}:{line}")
        return "source " + ", ".join(rendered_locations)

    summary = report["summary"]
    record_limit = report["limits"]["records"]
    lines = [
        f"DAG visualization ({report['view']})",
        (
            f"Records: {record_limit['returned_items']}/{record_limit['total_items']}"
            f"; intended relationships: {summary['intended_relationships']}"
            f"; observed relationships: {summary['observed_relationships']}"
        ),
    ]
    if record_limit["truncated"]:
        lines.append("Record output is truncated.")

    intention_names: dict[str, str] = {}
    reality_names: dict[str, str] = {}
    audit_ids: dict[tuple[str, str], str] = {}
    for record in report["records"]:
        classification = _plain_label(record.get("classification", "not compared"))
        if record["subject_kind"] in {"intention", "intent"}:
            node = record["intention"]
            name = display_name(node)
            intention_names[node["id"]] = name
            audit_ids[("Intention", node["id"])] = name
            label = "Intent" if record["subject_kind"] == "intent" else "Intention"
            lines.append(
                f"- {label}: {name} [{_plain_label(node['type'])}] — {classification}"
            )
            for candidate in record.get("reality_candidates", []):
                candidate_name = display_name(candidate)
                reality_names[candidate["id"]] = candidate_name
                audit_ids[("Reality", candidate["id"])] = candidate_name
                lines.append(
                    f"  - Reality: {candidate_name} "
                    f"[{_plain_label(candidate['type'])}] — {classification} — "
                    f"{source_suffix(candidate.get('source_evidence'))}"
                )
        else:
            node = record["reality"]
            name = display_name(node)
            reality_names[node["id"]] = name
            audit_ids[("Reality", node["id"])] = name
            lines.append(
                f"- Reality: {name} [{_plain_label(node['type'])}] — "
                f"{classification} — {source_suffix(record.get('source_evidence'))}"
            )

    def append_relationships(
        relationships: Iterable[Mapping[str, Any]],
        *,
        heading: str,
        names: Mapping[str, str],
        kind: str,
    ) -> None:
        for relationship in relationships:
            source_id = relationship["source_id"]
            target_id = relationship["target_id"]
            source_name = names.get(source_id)
            target_name = names.get(target_id)
            if source_name is None or target_name is None:
                audit_ids.setdefault((kind, source_id), "Record omitted by bounds")
                audit_ids.setdefault((kind, target_id), "Record omitted by bounds")
                lines.append(
                    f"- {heading}: endpoint names unavailable within the record bound"
                )
                continue
            relation_type = _plain_label(relationship["type"], limit=40)
            line = f"- {heading}: {source_name} --{relation_type}--> {target_name}"
            if relationship.get("description"):
                line += f" — {_plain_label(relationship['description'])}"
            lines.append(line)

    append_relationships(
        report.get("intended_relationships", []),
        heading="Intended",
        names=intention_names,
        kind="Intention",
    )
    append_relationships(
        report.get("observed_relationships", []),
        heading="Observed",
        names=reality_names,
        kind="Reality",
    )

    lines.extend(["", "Audit IDs"])
    for (kind, canonical_id), name in sorted(audit_ids.items()):
        lines.append(f"- {kind}: {_plain_label(name)} — {canonical_id}")
    return "\n".join(lines)


def render_dag(report: Mapping[str, Any], output_format: str) -> str:
    """Render one report through the shared CLI/MCP format contract."""

    if not isinstance(output_format, str):
        raise TypeError("output_format must be a string")
    normalized = output_format.casefold()
    if normalized == "json":
        return json.dumps(report, indent=2)
    if normalized == "human":
        return render_dag_human(report)
    if normalized == "mermaid":
        return render_dag_mermaid(report)
    raise DAGVisualizationError(f"Unsupported output format: {output_format}")
