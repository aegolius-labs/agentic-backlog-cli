# aio-sdlc-node: 9015c8a3-fd14-5598-916d-d03fcf41e415
"""Deterministic, evidence-gated reconciliation of intent and observed reality."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Node

REPORT_SCHEMA_VERSION = 1
DEFAULT_MAX_ITEMS = 100
CLASSIFICATION_PRIORITY = {
    "confirmed": 0,
    "candidate": 1,
    "ambiguous": 2,
    "unmapped": 3,
}


def normalize_node_name(value: str) -> str:
    """Return a conservative comparison key without inferring semantics."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^a-z0-9]+", "", normalized)


def _node_summary(node: Node) -> dict[str, str]:
    return {"id": node.id, "type": node.type.value, "name": node.name}


def write_reconciliation_report(report: dict[str, Any], output: str | Path) -> None:
    """Atomically persist one derived reconciliation report."""

    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
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
        confirmed_reality_ids: set[str],
        candidate_claims: Counter[str],
    ) -> dict[str, Any]:
        if intent_node.id in self.reality.nodes:
            reality_node = self.reality.nodes[intent_node.id]
            return {
                "subject_kind": "intent",
                "classification": "confirmed",
                "intent": _node_summary(intent_node),
                "reality_candidates": [_node_summary(reality_node)],
                "evidence": [{"kind": "canonical_guid", "value": intent_node.id}],
                "requires_approval": False,
            }

        normalized_name = normalize_node_name(intent_node.name)
        candidates = [
            node
            for node_id, node in self.reality.nodes.items()
            if node_id not in confirmed_reality_ids
            and node.type == intent_node.type
            and normalize_node_name(node.name) == normalized_name
        ]
        candidates.sort(key=lambda node: node.id)

        candidate_is_contested = any(
            candidate_claims[node.id] > 1 for node in candidates
        )
        if len(candidates) == 1 and not candidate_is_contested:
            classification = "candidate"
        elif candidates:
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
                    "reality_ids": [
                        node.id for node in candidates if candidate_claims[node.id] > 1
                    ],
                }
            )

        return {
            "subject_kind": "intent",
            "classification": classification,
            "intent": _node_summary(intent_node),
            "reality_candidates": [_node_summary(node) for node in candidates],
            "evidence": evidence,
            "requires_approval": True,
        }

    def analyze(self, *, max_items: int = DEFAULT_MAX_ITEMS) -> dict[str, Any]:
        """Return a bounded report while retaining complete classification totals."""

        if isinstance(max_items, bool) or not isinstance(max_items, int):
            raise TypeError("max_items must be an integer")
        if max_items < 1:
            raise ValueError("max_items must be at least 1")

        confirmed_reality_ids = set(self.intention.nodes).intersection(
            self.reality.nodes
        )
        candidate_claims: Counter[str] = Counter()
        for intent_node in self.intention.nodes.values():
            if intent_node.id in confirmed_reality_ids:
                continue
            normalized_name = normalize_node_name(intent_node.name)
            candidate_claims.update(
                node_id
                for node_id, node in self.reality.nodes.items()
                if node_id not in confirmed_reality_ids
                and node.type == intent_node.type
                and normalize_node_name(node.name) == normalized_name
            )
        intent_records = [
            self._intent_record(
                self.intention.nodes[node_id],
                confirmed_reality_ids,
                candidate_claims,
            )
            for node_id in sorted(self.intention.nodes)
        ]
        intent_records.sort(
            key=lambda record: (
                CLASSIFICATION_PRIORITY[record["classification"]],
                record["intent"]["id"],
            )
        )
        unclassified_reality = [
            self.reality.nodes[node_id]
            for node_id in sorted(self.reality.nodes)
            if node_id not in confirmed_reality_ids
        ]
        reality_records = [
            {
                "subject_kind": "reality",
                "classification": "unclassified_reality",
                "reality": _node_summary(node),
                "evidence": [],
                "requires_approval": True,
            }
            for node in unclassified_reality
        ]

        summary = {
            "intention_nodes": len(self.intention.nodes),
            "reality_nodes": len(self.reality.nodes),
            "confirmed": sum(
                record["classification"] == "confirmed" for record in intent_records
            ),
            "candidate": sum(
                record["classification"] == "candidate" for record in intent_records
            ),
            "ambiguous": sum(
                record["classification"] == "ambiguous" for record in intent_records
            ),
            "unmapped": sum(
                record["classification"] == "unmapped" for record in intent_records
            ),
            "unclassified_reality": len(unclassified_reality),
        }
        all_items = intent_records + reality_records
        returned_items = all_items[:max_items]

        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "summary": summary,
            "limit": {
                "max_items": max_items,
                "total_items": len(all_items),
                "returned_items": len(returned_items),
                "truncated": len(returned_items) < len(all_items),
            },
            "items": returned_items,
        }
