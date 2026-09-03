"""Evidence-bound routing between safe reconciliation and implementation work."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import EdgeType, Node, NodeType
from aio_agentic_sdlc.diffing_engine import DiffingEngine, DiffPolicy
from aio_agentic_sdlc.intent_ir import ApprovalState

TRIAGE_SCHEMA_VERSION = 1
DEFAULT_MAX_ITEMS = 100
MAX_CRITERIA = 10
MAX_REQUIRED_EVIDENCE = 10
MAX_DISPLAY_TEXT = 500

DecisionText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]
EvidenceText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


class DriftTriageError(ValueError):
    """Raised for an expected invalid triage request, decision, or DAG identity."""


class DriftClassification(str, Enum):
    """Permitted explicit reconciliation-drift decisions."""

    MISSING_IMPLEMENTATION = "missing_implementation"
    OBSOLETE_OR_UNAPPROVED_INTENT = "obsolete_or_unapproved_intent"
    FRAMEWORK_TOOLING_DRIFT = "framework_tooling_drift"


class TriageDecision(BaseModel):
    """One auditable decision bound to an exact triage subject."""

    model_config = ConfigDict(extra="forbid")

    subject_key: DecisionText
    classification: DriftClassification
    rationale: DecisionText
    evidence: list[EvidenceText] = Field(min_length=1, max_length=20)
    decided_by: DecisionText
    decided_at: datetime

    @field_validator("decided_at")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise DriftTriageError("decided_at must be timezone-aware")
        return value


class TriageDecisionSet(BaseModel):
    """Explicit decisions for one exact Intention/Reality plan identity."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    decisions: list[TriageDecision] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def reject_duplicate_subjects(self):
        keys = [decision.subject_key for decision in self.decisions]
        if len(keys) != len(set(keys)):
            raise DriftTriageError(
                "triage decisions contain duplicate subject_key values"
            )
        return self


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _feed_digest(digest, label: str, payload: Any) -> None:
    encoded = _canonical_json({"label": label, "payload": payload})
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _canonical_dag_sha256(manager: DAGManager) -> str:
    """Hash validated DAG content independently of YAML order and line endings."""

    canonical_nodes: dict[str, Node] = {}
    for source_id, node in manager.nodes.items():
        canonical_id = str(UUID(source_id))
        if canonical_id in canonical_nodes:
            raise DriftTriageError(
                f"DAG contains duplicate canonical GUID {canonical_id}"
            )
        canonical_nodes[canonical_id] = node

    digest = hashlib.sha256()
    _feed_digest(
        digest,
        "metadata",
        manager.metadata.model_dump(mode="json", exclude_none=True),
    )
    for canonical_id in sorted(canonical_nodes):
        payload = canonical_nodes[canonical_id].model_dump(
            mode="json",
            exclude_none=True,
        )
        payload["id"] = canonical_id
        _feed_digest(digest, "node", payload)

    canonical_edges = []
    for edge in manager.edges:
        payload = edge.model_dump(mode="json", exclude_none=True)
        payload["source"] = str(UUID(edge.source))
        payload["target"] = str(UUID(edge.target))
        canonical_edges.append(payload)
    for payload in sorted(
        canonical_edges,
        key=lambda item: (
            item["source"],
            item["target"],
            item["type"],
            item.get("description", ""),
        ),
    ):
        _feed_digest(digest, "edge", payload)
    return digest.hexdigest()


def _bounded_text(value: str, *, limit: int = MAX_DISPLAY_TEXT) -> tuple[str, bool]:
    if len(value) <= limit:
        return value, False
    return value[:limit], True


def _bounded_strings(values: list[str], *, limit: int) -> dict[str, Any]:
    retained = []
    for value in values[:limit]:
        text, truncated = _bounded_text(value)
        retained.append({"value": text, "value_truncated": truncated})
    return {
        "items": retained,
        "total_items": len(values),
        "returned_items": len(retained),
        "truncated": len(retained) < len(values),
    }


def _acceptance_criteria(node: Node) -> dict[str, Any]:
    criteria = node.intent.acceptance_criteria if node.intent else []
    retained = []
    for criterion in criteria[:MAX_CRITERIA]:
        statement, statement_truncated = _bounded_text(criterion.statement)
        evidence = _bounded_strings(
            list(criterion.required_evidence),
            limit=MAX_REQUIRED_EVIDENCE,
        )
        criterion_id, criterion_id_truncated = _bounded_text(criterion.id)
        retained.append(
            {
                "id": criterion_id,
                "id_truncated": criterion_id_truncated,
                "statement": statement,
                "statement_truncated": statement_truncated,
                "required_evidence": evidence,
            }
        )
    return {
        "items": retained,
        "total_items": len(criteria),
        "returned_items": len(retained),
        "truncated": len(retained) < len(criteria),
    }


def _approval_state(node: Node) -> str:
    if node.intent is None:
        return "missing_intent_ir"
    return node.intent.approval.state.value


def _is_approved(node: Node) -> bool:
    return (
        node.intent is not None and node.intent.approval.state == ApprovalState.APPROVED
    )


def _relationship_is_observable(
    source: Node,
    target: Node,
    relation: EdgeType,
) -> bool:
    """Return whether the current Reality parser can emit this relationship shape."""

    if relation == EdgeType.CONTAINS:
        return True
    if relation == EdgeType.DEPENDS_ON:
        return source.type == NodeType.MODULE and target.type == NodeType.MODULE
    return False


def _subject_name(node: Node) -> dict[str, Any]:
    name, truncated = _bounded_text(node.name)
    return {
        "type": node.type.value,
        "name": name,
        "name_truncated": truncated,
    }


class DriftTriageEngine:
    """Classify safe reconciliation work without mutating DAG or backlog state."""

    _classification_order = (
        "missing_implementation",
        "needs_classification",
        "identity_review_required",
        "framework_tooling_drift",
        "obsolete_or_unapproved_intent",
    )

    def __init__(self, intention: DAGManager, reality: DAGManager):
        intention.validate()
        reality.validate()
        self.intention = intention
        self.reality = reality
        self._intent_by_canonical_id = self._canonical_node_index(
            intention,
            dag_name="Intention DAG",
        )

    @staticmethod
    def _canonical_node_index(
        manager: DAGManager,
        *,
        dag_name: str,
    ) -> dict[str, Node]:
        index: dict[str, Node] = {}
        for source_id, node in manager.nodes.items():
            canonical_id = str(UUID(source_id))
            if canonical_id in index:
                raise DriftTriageError(
                    f"{dag_name} contains duplicate canonical GUID {canonical_id}"
                )
            index[canonical_id] = node
        return index

    @staticmethod
    def _validate_limit(value: int) -> None:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("max_items must be an integer")
        if value < 1:
            raise DriftTriageError("max_items must be at least 1")

    def source_identity(self) -> dict[str, str]:
        intention_sha256 = _canonical_dag_sha256(self.intention)
        reality_sha256 = _canonical_dag_sha256(self.reality)
        plan_digest = hashlib.sha256(
            _canonical_json(
                {
                    "triage_contract": TRIAGE_SCHEMA_VERSION,
                    "intention_sha256": intention_sha256,
                    "reality_sha256": reality_sha256,
                }
            )
        ).hexdigest()
        return {
            "intention_sha256": intention_sha256,
            "reality_sha256": reality_sha256,
            "plan_digest": plan_digest,
        }

    def _full_safe_plan(self) -> dict[str, Any]:
        maximum_tasks = max(1, len(self.intention.nodes) + len(self.intention.edges))
        plan = DiffingEngine(
            self.intention,
            self.reality,
            policy=DiffPolicy.safe(max_tasks=maximum_tasks),
        ).calculate_diff()
        if plan["meta"]["truncated"]:
            raise DriftTriageError(
                "internal safe plan bound did not retain every triage subject"
            )
        return plan

    @staticmethod
    def _decision_payload(decision: TriageDecision) -> dict[str, Any]:
        return {
            "rationale": decision.rationale,
            "evidence": list(decision.evidence),
            "decided_by": decision.decided_by,
            "decided_at": decision.decided_at.isoformat(),
        }

    def _intent_item(
        self,
        task: dict[str, Any],
        decisions: dict[str, TriageDecision],
        used_decisions: set[str],
    ) -> dict[str, Any]:
        source_id = task.get("canonical_intent_id") or task["evidence"].get(
            "canonical_guid"
        )
        if source_id is None:
            raise DriftTriageError(
                f"safe task {task['action']} has no canonical intent ID"
            )
        canonical_id = str(UUID(source_id))
        node = self._intent_by_canonical_id[canonical_id]
        subject_key = f"intent:{canonical_id}"
        approval_state = _approval_state(node)
        action = task["action"]
        decision = decisions.get(subject_key)

        if action in {"review_mapping", "resolve_ambiguous_mapping"}:
            classification = "identity_review_required"
            reason = "Identity evidence must be resolved before implementation drift can be classified."
            decision_source = "identity_gate"
        elif not _is_approved(node):
            classification = "obsolete_or_unapproved_intent"
            reason = (
                f"Intent approval state is {approval_state}; implementation is withheld "
                "until the canonical intent is approved or retired."
            )
            decision_source = "approval_gate"
        elif decision is None:
            classification = "needs_classification"
            reason = (
                "Approved intent has no deterministic Reality match; explicit evidence is "
                "required to distinguish missing implementation from tooling drift."
            )
            decision_source = "pending"
        else:
            classification = decision.classification.value
            reason = decision.rationale
            decision_source = "explicit"
            used_decisions.add(subject_key)

        subject = {"kind": "intent", **_subject_name(node)}
        item = {
            "subject": subject,
            "classification": classification,
            "reason": reason,
            "decision_source": decision_source,
            "implementation_authorized": classification
            == DriftClassification.MISSING_IMPLEMENTATION.value
            and _is_approved(node),
            "evidence": {
                "approval_state": approval_state,
                "safe_action": action,
                "acceptance_criteria": _acceptance_criteria(node),
            },
            "audit": {
                "subject_key": subject_key,
                "canonical_intent_id": canonical_id,
            },
        }
        if decision_source == "explicit":
            item["decision"] = self._decision_payload(decision)
        return item

    def _relationship_item(
        self,
        task: dict[str, Any],
        decisions: dict[str, TriageDecision],
        used_decisions: set[str],
    ) -> dict[str, Any]:
        relationship = task["evidence"]["relationship"]
        source_id = str(UUID(relationship["source_id"]))
        target_id = str(UUID(relationship["target_id"]))
        relation = EdgeType(relationship["type"])
        source = self._intent_by_canonical_id[source_id]
        target = self._intent_by_canonical_id[target_id]
        subject_key = f"relationship:{source_id}:{relation.value}:{target_id}"
        decision = decisions.get(subject_key)

        if not _is_approved(source) or not _is_approved(target):
            classification = "obsolete_or_unapproved_intent"
            reason = (
                "At least one relationship endpoint is not approved; no implementation "
                "work may be inferred from the missing observation."
            )
            decision_source = "approval_gate"
        elif not _relationship_is_observable(source, target, relation):
            classification = "framework_tooling_drift"
            reason = (
                f"The current Reality parser does not emit {relation.value} relationships "
                f"for {source.type.value}-to-{target.type.value} endpoints."
            )
            decision_source = "observation_contract"
        elif decision is None:
            classification = "needs_classification"
            reason = (
                "The relationship is observable in principle, but absence alone does not "
                "prove missing implementation."
            )
            decision_source = "pending"
        else:
            classification = decision.classification.value
            reason = decision.rationale
            decision_source = "explicit"
            used_decisions.add(subject_key)

        item = {
            "subject": {
                "kind": "relationship",
                "source": _subject_name(source),
                "relation": relation.value,
                "target": _subject_name(target),
            },
            "classification": classification,
            "reason": reason,
            "decision_source": decision_source,
            "implementation_authorized": classification
            == DriftClassification.MISSING_IMPLEMENTATION.value
            and _is_approved(source)
            and _is_approved(target),
            "evidence": {
                "source_approval_state": _approval_state(source),
                "target_approval_state": _approval_state(target),
                "safe_action": task["action"],
                "relationship_observable": _relationship_is_observable(
                    source,
                    target,
                    relation,
                ),
            },
            "audit": {
                "subject_key": subject_key,
                "source_intent_id": source_id,
                "target_intent_id": target_id,
            },
        }
        if decision_source == "explicit":
            item["decision"] = self._decision_payload(decision)
        return item

    def analyze(
        self,
        *,
        decisions: TriageDecisionSet | None = None,
        max_items: int = DEFAULT_MAX_ITEMS,
    ) -> dict[str, Any]:
        """Return a bounded triage report with complete classification totals."""

        self._validate_limit(max_items)
        source = self.source_identity()
        if decisions is not None and decisions.plan_digest != source["plan_digest"]:
            raise DriftTriageError(
                "stale triage decisions: plan_digest does not match current DAG state"
            )
        decision_index = {
            decision.subject_key: decision
            for decision in (decisions.decisions if decisions else [])
        }
        used_decisions: set[str] = set()
        plan = self._full_safe_plan()
        summary = {
            "plan_tasks": plan["meta"]["total_tasks"],
            "missing_implementation": 0,
            "obsolete_or_unapproved_intent": 0,
            "framework_tooling_drift": 0,
            "identity_review_required": 0,
            "needs_classification": 0,
            "actionable_implementation": 0,
        }
        retained = {classification: [] for classification in self._classification_order}

        for task in plan["nodes"].values():
            if task["action"] == "connect_confirmed":
                item = self._relationship_item(task, decision_index, used_decisions)
            else:
                item = self._intent_item(task, decision_index, used_decisions)
            classification = item["classification"]
            summary[classification] += 1
            if item["implementation_authorized"]:
                summary["actionable_implementation"] += 1
            bucket = retained[classification]
            if len(bucket) < max_items:
                bucket.append(item)

        unused = sorted(set(decision_index).difference(used_decisions))
        if unused:
            raise DriftTriageError(
                "triage decisions reference unknown or inapplicable subjects: "
                + ", ".join(unused)
            )

        items = []
        for classification in self._classification_order:
            remaining = max_items - len(items)
            if remaining == 0:
                break
            items.extend(retained[classification][:remaining])

        total_items = summary["plan_tasks"]
        return {
            "schema_version": TRIAGE_SCHEMA_VERSION,
            "source": source,
            "summary": summary,
            "limit": {
                "max_items": max_items,
                "total_items": total_items,
                "returned_items": len(items),
                "truncated": len(items) < total_items,
            },
            "items": items,
        }


def _subject_label(subject: dict[str, Any]) -> str:
    if subject["kind"] == "intent":
        return f"{subject['type'].capitalize()} '{subject['name']}'"
    source = subject["source"]
    target = subject["target"]
    return (
        f"{source['type'].capitalize()} '{source['name']}' "
        f"{subject['relation']} {target['type'].capitalize()} '{target['name']}'"
    )


def render_drift_triage(report: dict[str, Any]) -> str:
    """Render a GUID-last human brief from a drift triage report."""

    summary = report["summary"]
    limit = report["limit"]
    lines = [
        "Reconciliation drift triage",
        "",
        f"{limit['returned_items']} of {limit['total_items']} triage items shown.",
        f"Actionable missing implementation: {summary['actionable_implementation']}",
        f"Needs classification: {summary['needs_classification']}",
        f"Identity review required: {summary['identity_review_required']}",
        f"Framework tooling drift: {summary['framework_tooling_drift']}",
        f"Obsolete or unapproved intent: {summary['obsolete_or_unapproved_intent']}",
        "",
    ]
    for item in report["items"]:
        classification = item["classification"].replace("_", " ")
        lines.extend(
            [
                f"- {_subject_label(item['subject'])}: {classification}",
                f"  Reason: {item['reason']}",
                "  Implementation authorized: "
                + ("yes" if item["implementation_authorized"] else "no"),
            ]
        )

    lines.extend(["", "Audit", f"Plan digest: {report['source']['plan_digest']}"])
    for item in report["items"]:
        lines.append(
            f"- {_subject_label(item['subject'])}: {item['audit']['subject_key']}"
        )
    return "\n".join(lines)
