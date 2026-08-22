# aio-sdlc-node: 9015c8a3-fd14-5598-916d-d03fcf41e415
"""Deterministic, evidence-gated reconciliation of intent and observed reality."""

from __future__ import annotations

import json
import os
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from uuid import UUID

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Node, NodeType
from aio_agentic_sdlc.dag_store import guarded_file_path

REPORT_SCHEMA_VERSION = 1
DEFAULT_MAX_ITEMS = 100
DEFAULT_MAX_CANDIDATES = 20
PROTECTED_STATE_FILENAMES = {
    "intention-dag.yaml",
    "reality-dag.yaml",
    "backlog.json",
    "state-audit.jsonl",
    "state.lock",
}
CLASSIFICATION_PRIORITY = {
    "confirmed": 0,
    "candidate": 1,
    "ambiguous": 2,
    "unmapped": 3,
}


class ReconciliationError(ValueError):
    """Raised for an expected invalid reconciliation request or identity."""


def normalize_node_name(value: str) -> str:
    """Return a conservative comparison key without inferring semantics."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _node_summary(node: Node) -> dict[str, str]:
    return {"id": node.id, "type": node.type.value, "name": node.name}


def _canonical_guid_index(
    nodes: dict[str, Node],
    *,
    dag_name: str,
) -> dict[str, str]:
    index: dict[str, str] = {}
    for source_id in nodes:
        canonical_id = str(UUID(source_id))
        if canonical_id in index:
            raise ReconciliationError(
                f"{dag_name} contains duplicate canonical GUID {canonical_id}: "
                f"{index[canonical_id]} and {source_id}"
            )
        index[canonical_id] = source_id
    return index


def validate_reconciliation_report_output(
    output: str | Path,
    *,
    protected_paths: tuple[str | Path, ...] = (),
) -> Path:
    """Resolve a report target and reject protected framework state aliases."""

    target = guarded_file_path(output, create_parent=True)
    target_identity = os.path.normcase(str(target))
    protected_identities = {
        os.path.normcase(os.path.abspath(os.fspath(path))) for path in protected_paths
    }
    if (
        target.name.casefold() in PROTECTED_STATE_FILENAMES
        or target_identity in protected_identities
    ):
        raise ReconciliationError(
            f"Refusing to overwrite protected framework state with a report: {target}"
        )
    return target


def write_reconciliation_report(
    report: dict[str, Any],
    output: str | Path,
    *,
    protected_paths: tuple[str | Path, ...] = (),
) -> None:
    """Atomically persist one derived reconciliation report."""

    target = validate_reconciliation_report_output(
        output,
        protected_paths=protected_paths,
    )
    target = guarded_file_path(target)
    descriptor, temporary = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class ReconciliationEngine:
    """Classify deterministic identity evidence without mutating either DAG."""

    def __init__(self, intention: DAGManager, reality: DAGManager):
        self.intention = intention
        self.reality = reality

    def _intent_record(
        self,
        intent_node: Node,
        confirmed_reality_by_canonical_id: dict[str, str],
        candidate_index: dict[tuple[NodeType, str], list[str]],
        candidate_claims: Counter[tuple[NodeType, str]],
        max_candidates: int,
    ) -> dict[str, Any]:
        canonical_intent_id = str(UUID(intent_node.id))
        if canonical_intent_id in confirmed_reality_by_canonical_id:
            reality_source_id = confirmed_reality_by_canonical_id[canonical_intent_id]
            reality_node = self.reality.nodes[reality_source_id]
            canonical_evidence = {
                "kind": "canonical_guid",
                "value": canonical_intent_id,
            }
            if intent_node.id != reality_source_id:
                canonical_evidence.update(
                    {
                        "intent_source_id": intent_node.id,
                        "reality_source_id": reality_source_id,
                    }
                )
            return {
                "subject_kind": "intent",
                "classification": "confirmed",
                "intent": _node_summary(intent_node),
                "reality_candidates": [_node_summary(reality_node)],
                "evidence": [canonical_evidence],
                "requires_approval": False,
            }

        normalized_name = normalize_node_name(intent_node.name)
        candidate_key = (intent_node.type, normalized_name)
        candidate_ids = (
            candidate_index.get(candidate_key, []) if normalized_name else []
        )
        total_candidates = len(candidate_ids)
        candidates = [
            self.reality.nodes[node_id] for node_id in candidate_ids[:max_candidates]
        ]
        candidate_is_contested = (
            total_candidates > 0 and candidate_claims[candidate_key] > 1
        )
        total_contested_candidates = total_candidates if candidate_is_contested else 0
        if total_candidates == 1 and not candidate_is_contested:
            classification = "candidate"
        elif total_candidates:
            classification = "ambiguous"
        else:
            classification = "unmapped"

        evidence: list[dict[str, Any]] = []
        if candidates:
            evidence.append(
                {
                    "kind": "normalized_name_and_type",
                    "normalized_name": normalized_name,
                    "node_type": intent_node.type.value,
                }
            )
        if candidate_is_contested:
            evidence.append(
                {
                    "kind": "candidate_shared_by_multiple_intents",
                    "total_shared_candidates": total_contested_candidates,
                }
            )

        return {
            "subject_kind": "intent",
            "classification": classification,
            "intent": _node_summary(intent_node),
            "reality_candidates": [_node_summary(node) for node in candidates],
            "candidate_limit": {
                "max_candidates": max_candidates,
                "total_candidates": total_candidates,
                "returned_candidates": len(candidates),
                "truncated": len(candidates) < total_candidates,
            },
            "evidence": evidence,
            "requires_approval": True,
        }

    @staticmethod
    def _validate_limit(value: int, *, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer")
        if value < 1:
            raise ReconciliationError(f"{name} must be at least 1")

    def _classification_context(self) -> dict[str, Any]:
        intention_by_canonical_id = _canonical_guid_index(
            self.intention.nodes,
            dag_name="Intention DAG",
        )
        reality_by_canonical_id = _canonical_guid_index(
            self.reality.nodes,
            dag_name="Reality DAG",
        )
        confirmed_canonical_ids = set(intention_by_canonical_id).intersection(
            reality_by_canonical_id
        )
        confirmed_reality_by_canonical_id = {
            canonical_id: reality_by_canonical_id[canonical_id]
            for canonical_id in confirmed_canonical_ids
        }
        confirmed_reality_ids = set(confirmed_reality_by_canonical_id.values())

        candidate_index: dict[tuple[NodeType, str], list[str]] = defaultdict(list)
        for node_id in sorted(self.reality.nodes):
            if node_id in confirmed_reality_ids:
                continue
            node = self.reality.nodes[node_id]
            normalized_name = normalize_node_name(node.name)
            if normalized_name:
                candidate_index[(node.type, normalized_name)].append(node_id)

        candidate_claims: Counter[tuple[NodeType, str]] = Counter()
        for intent_node in self.intention.nodes.values():
            if str(UUID(intent_node.id)) in confirmed_canonical_ids:
                continue
            normalized_name = normalize_node_name(intent_node.name)
            if normalized_name:
                candidate_claims[(intent_node.type, normalized_name)] += 1

        return {
            "confirmed_canonical_ids": confirmed_canonical_ids,
            "confirmed_reality_by_canonical_id": confirmed_reality_by_canonical_id,
            "candidate_index": candidate_index,
            "candidate_claims": candidate_claims,
        }

    def _iter_intent_records(
        self,
        context: dict[str, Any],
        *,
        max_candidates: int,
    ):
        for node_id in sorted(self.intention.nodes):
            yield self._intent_record(
                self.intention.nodes[node_id],
                context["confirmed_reality_by_canonical_id"],
                context["candidate_index"],
                context["candidate_claims"],
                max_candidates,
            )

    def iter_intent_records(
        self,
        *,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
    ):
        """Yield deterministic, bounded intent records without retaining them all."""

        self._validate_limit(max_candidates, name="max_candidates")
        context = self._classification_context()
        yield from self._iter_intent_records(
            context,
            max_candidates=max_candidates,
        )

    def analyze(
        self,
        *,
        max_items: int = DEFAULT_MAX_ITEMS,
        max_candidates: int = DEFAULT_MAX_CANDIDATES,
    ) -> dict[str, Any]:
        """Return a bounded report while retaining complete classification totals."""

        self._validate_limit(max_items, name="max_items")
        self._validate_limit(max_candidates, name="max_candidates")
        context = self._classification_context()
        classification_counts = {
            classification: 0 for classification in CLASSIFICATION_PRIORITY
        }
        retained_by_classification: dict[str, list[dict[str, Any]]] = {
            classification: [] for classification in CLASSIFICATION_PRIORITY
        }
        for record in self._iter_intent_records(
            context,
            max_candidates=max_candidates,
        ):
            classification = record["classification"]
            classification_counts[classification] += 1
            if len(retained_by_classification[classification]) < max_items:
                retained_by_classification[classification].append(record)

        intent_records: list[dict[str, Any]] = []
        for classification in sorted(
            CLASSIFICATION_PRIORITY,
            key=CLASSIFICATION_PRIORITY.get,
        ):
            remaining = max_items - len(intent_records)
            if remaining == 0:
                break
            intent_records.extend(
                retained_by_classification[classification][:remaining]
            )

        confirmed_canonical_ids = context["confirmed_canonical_ids"]
        confirmed_reality_ids = set(
            context["confirmed_reality_by_canonical_id"].values()
        )
        unclassified_reality_count = len(self.reality.nodes) - len(
            confirmed_canonical_ids
        )
        remaining = max_items - len(intent_records)
        reality_records = []
        if remaining:
            for node_id in sorted(self.reality.nodes):
                if node_id in confirmed_reality_ids:
                    continue
                reality_records.append(
                    {
                        "subject_kind": "reality",
                        "classification": "unclassified_reality",
                        "reality": _node_summary(self.reality.nodes[node_id]),
                        "evidence": [],
                        "requires_approval": True,
                    }
                )
                if len(reality_records) == remaining:
                    break

        summary = {
            "intention_nodes": len(self.intention.nodes),
            "reality_nodes": len(self.reality.nodes),
            **classification_counts,
            "unclassified_reality": unclassified_reality_count,
        }
        all_items = intent_records + reality_records
        total_items = len(self.intention.nodes) + unclassified_reality_count

        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "summary": summary,
            "limit": {
                "max_items": max_items,
                "total_items": total_items,
                "returned_items": len(all_items),
                "truncated": len(all_items) < total_items,
            },
            "items": all_items,
        }
