"""Deterministic, review-gated migration of legacy Intention DAG nodes."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .dag_manager import DAGManager
from .dag_models import Edge, Node
from .dag_store import dag_file_lock, guarded_dag_path
from .intent_ir import (
    AcceptanceCriterion,
    Ambiguity,
    AmbiguityStatus,
    Approval,
    ApprovalState,
    IntentIR,
    IntentRevision,
    Provenance,
    ProvenanceType,
)
from .workspace import (
    ARCHIVE_DIR,
    INBOX_DIR,
    INTENTION_DAG_FILE,
    RESEARCH_SPIKES_DIR,
    SPECS_DIR,
    workspace_file_path,
)

MIGRATION_SCHEMA_VERSION = 1
DEFAULT_MAX_ITEMS = 100
MAX_DOCUMENT_PROVENANCE = 3
DOCUMENT_DIRECTORIES = (SPECS_DIR, ARCHIVE_DIR, INBOX_DIR, RESEARCH_SPIKES_DIR)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _edge_key(edge: Edge) -> tuple[str, str, str, str]:
    return (edge.source, edge.target, edge.type.value, edge.description or "")


class LegacyIntentMigrator:
    """Inventory, compile, and atomically apply review-required legacy intent."""

    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.dag_path = workspace_file_path(
            self.project_root,
            INTENTION_DAG_FILE,
            create_parent=False,
        )
        if not self.dag_path.exists():
            raise ValueError(f"Canonical Intention DAG does not exist: {self.dag_path}")

    def _manager(self) -> DAGManager:
        return DAGManager.load(str(guarded_dag_path(self.dag_path)))

    @staticmethod
    def _dag_content_sha256(manager: DAGManager) -> str:
        """Hash validated DAG content independently of checkout serialization."""

        payload = {
            "metadata": manager.metadata.model_dump(mode="json", exclude_none=True),
            "nodes": [
                node.model_dump(mode="json", exclude_none=True)
                for node in manager.nodes.values()
            ],
            "edges": [
                edge.model_dump(mode="json", exclude_none=True)
                for edge in manager.edges
            ],
        }
        return _sha256(_canonical_json(payload))

    @staticmethod
    def _legacy_nodes(manager: DAGManager) -> list[Node]:
        return sorted(
            (node for node in manager.nodes.values() if node.intent is None),
            key=lambda node: node.id.casefold(),
        )

    @staticmethod
    def _related_edges(manager: DAGManager, node_id: str) -> list[Edge]:
        return sorted(
            (
                edge
                for edge in manager.edges
                if edge.source == node_id or edge.target == node_id
            ),
            key=_edge_key,
        )

    @classmethod
    def _node_fingerprint(cls, manager: DAGManager, node: Node) -> str:
        payload = {
            "node": node.model_dump(mode="json", exclude={"intent"}, exclude_none=True),
            "edges": [
                edge.model_dump(mode="json", exclude_none=True)
                for edge in cls._related_edges(manager, node.id)
            ],
        }
        return _sha256(_canonical_json(payload))

    def _inventory_locked(self, *, max_items: int) -> dict[str, Any]:
        if max_items < 0:
            raise ValueError("max_items must be zero or greater")
        manager = self._manager()
        legacy = self._legacy_nodes(manager)
        returned = legacy[:max_items]
        return {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "source": {
                "path": INTENTION_DAG_FILE,
                "sha256": self._dag_content_sha256(manager),
            },
            "summary": {
                "total_nodes": len(manager.nodes),
                "intent_ir_nodes": len(manager.nodes) - len(legacy),
                "legacy_nodes": len(legacy),
            },
            "limit": {
                "max_items": max_items,
                "total_items": len(legacy),
                "returned_items": len(returned),
                "truncated": len(returned) < len(legacy),
            },
            "items": [
                {
                    "node_id": node.id,
                    "type": node.type.value,
                    "name": node.name,
                    "domain": node.domain,
                    "has_description": bool(node.description),
                    "relationship_count": len(self._related_edges(manager, node.id)),
                }
                for node in returned
            ],
        }

    def inventory(self, *, max_items: int = DEFAULT_MAX_ITEMS) -> dict[str, Any]:
        """Return complete totals with bounded, deterministic legacy-node detail."""

        with dag_file_lock(self.dag_path):
            return self._inventory_locked(max_items=max_items)

    def _document_title_index(self) -> dict[str, list[Provenance]]:
        """Index exact document titles once without inferring from body mentions."""

        index: dict[str, list[Provenance]] = {}
        for directory in DOCUMENT_DIRECTORIES:
            root = self.project_root / directory
            if not root.exists():
                continue
            if root.is_symlink() or not root.is_dir():
                raise ValueError(f"Legacy document directory is not safe: {root}")
            for document in sorted(root.rglob("*.md")):
                if document.is_symlink() or not document.is_file():
                    raise ValueError(
                        f"Legacy source document is not a regular file: {document}"
                    )
                title_record = self._document_title(
                    document.read_text(encoding="utf-8").splitlines()
                )
                if title_record is not None:
                    line_number, statement, title = title_record
                    key = self._normalized_document_title(title)
                    if key:
                        relative = document.relative_to(self.project_root).as_posix()
                        index.setdefault(key, []).append(
                            Provenance(
                                source_type=ProvenanceType.DOCUMENT,
                                reference=f"{relative}:{line_number}",
                                statement=statement,
                            )
                        )
        return index

    @staticmethod
    def _document_title(lines: list[str]) -> tuple[int, str, str] | None:
        start = 0
        if lines and lines[0].strip() == "---":
            for index, raw_line in enumerate(lines[1:], start=1):
                statement = raw_line.strip()
                if statement == "---":
                    start = index + 1
                    break
                if statement.casefold().startswith("title:"):
                    title = statement.split(":", 1)[1].strip().strip("\"'")
                    return index + 1, statement, title
        for index, raw_line in enumerate(lines[start:], start=start):
            statement = raw_line.strip()
            if statement.startswith("# "):
                return index + 1, statement, statement[2:].strip()
        return None

    @staticmethod
    def _normalized_document_title(value: str) -> str:
        normalized = value.casefold().strip().strip("\"'")
        normalized = re.sub(
            r"^(product requirement document|software design document|specification)"
            r"\s*(?:\([^)]*\))?\s*[:\-]\s*",
            "",
            normalized,
        )
        normalized = re.sub(
            r"\s+(?:product requirement document|software design document|"
            r"specification|prd|sdd)$",
            "",
            normalized,
        )
        return "".join(character for character in normalized if character.isalnum())

    def _compile_intent(
        self,
        manager: DAGManager,
        node: Node,
        *,
        recorded_at: datetime,
        actor: str,
        generator_version: str,
        document_index: dict[str, list[Provenance]],
    ) -> IntentIR:
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")

        statement = node.description.strip() if node.description else node.name.strip()
        provenance = [
            Provenance(
                source_type=ProvenanceType.IMPORTED_SPEC,
                reference=f"{INTENTION_DAG_FILE}#node:{node.id}",
                statement=statement,
            )
        ]
        described_edges = [
            edge
            for edge in self._related_edges(manager, node.id)
            if edge.description and edge.description.strip()
        ]
        provenance.extend(
            Provenance(
                source_type=ProvenanceType.IMPORTED_SPEC,
                reference=(
                    f"{INTENTION_DAG_FILE}#edge:{edge.source}:"
                    f"{edge.type.value}:{edge.target}"
                ),
                statement=edge.description.strip(),
            )
            for edge in described_edges
        )
        matching_documents = document_index.get(
            self._normalized_document_title(node.name),
            [],
        )
        documents = matching_documents[:MAX_DOCUMENT_PROVENANCE]
        total_documents = len(matching_documents)
        provenance.extend(documents)

        confidence = 0.35
        if node.description:
            confidence += 0.2
        if described_edges:
            confidence += 0.1
        if documents:
            confidence += 0.1

        assumptions = [
            "The preserved node description is the complete locally available statement of legacy intent.",
            "Existing graph relationships remain authoritative structural context.",
        ]
        ambiguity_question = (
            f"Does this mechanically compiled payload fully capture the original intent "
            f"for {node.name}?"
        )
        if not node.description:
            ambiguity_question = (
                f"What behavior was originally intended for {node.name}, which has no "
                "preserved description?"
            )

        ambiguities = [
            Ambiguity(
                question=ambiguity_question,
                status=AmbiguityStatus.OPEN,
            )
        ]
        omitted_documents = total_documents - len(documents)
        if omitted_documents:
            ambiguities.append(
                Ambiguity(
                    question=(
                        f"Which of the {omitted_documents} additional exact-title "
                        f"documents for {node.name} should be treated as authoritative?"
                    ),
                    status=AmbiguityStatus.OPEN,
                )
            )

        return IntentIR(
            provenance=provenance,
            assumptions=assumptions,
            ambiguities=ambiguities,
            confidence=min(confidence, 0.75),
            acceptance_criteria=[
                AcceptanceCriterion(
                    id=f"LEGACY-{node.id}-AC1",
                    statement=statement,
                    required_evidence=[f"reconciliation:intent:{node.id}"],
                )
            ],
            revision_history=[
                IntentRevision(
                    revision=1,
                    recorded_at=recorded_at,
                    actor=actor,
                    generator_version=generator_version,
                    summary=(
                        "Mechanically migrated preserved legacy intent; human review "
                        "remains required."
                    ),
                )
            ],
            responsible_agent="sdlc_cartographer",
            generator_version=generator_version,
            approval=Approval(
                state=ApprovalState.REVIEW_REQUIRED,
                rationale=(
                    "Mechanical migration preserves available sources but does not "
                    "claim semantic completeness."
                ),
            ),
        )

    def _plan_locked(
        self,
        *,
        recorded_at: datetime,
        actor: str,
        generator_version: str,
    ) -> dict[str, Any]:
        """Compile a deterministic, review-required plan for every legacy node."""

        manager = self._manager()
        legacy = self._legacy_nodes(manager)
        document_index = self._document_title_index()
        source_hash = self._dag_content_sha256(manager)
        items = []
        for node in legacy:
            intent = self._compile_intent(
                manager,
                node,
                recorded_at=recorded_at,
                actor=actor,
                generator_version=generator_version,
                document_index=document_index,
            )
            items.append(
                {
                    "node_id": node.id,
                    "node_fingerprint": self._node_fingerprint(manager, node),
                    "intent": intent.model_dump(mode="json"),
                }
            )

        plan = {
            "schema_version": MIGRATION_SCHEMA_VERSION,
            "source": {"path": INTENTION_DAG_FILE, "sha256": source_hash},
            "generated_at": recorded_at.isoformat(),
            "actor": actor,
            "generator_version": generator_version,
            "summary": {
                "total_nodes": len(manager.nodes),
                "already_migrated": len(manager.nodes) - len(legacy),
                "planned_migrations": len(legacy),
                "approval_state": ApprovalState.REVIEW_REQUIRED.value,
            },
            "items": items,
        }
        plan["plan_sha256"] = _sha256(_canonical_json(plan))
        return plan

    def plan(
        self,
        *,
        recorded_at: datetime,
        actor: str,
        generator_version: str,
    ) -> dict[str, Any]:
        """Compile a coherent plan while excluding concurrent DAG writers."""

        with dag_file_lock(self.dag_path):
            return self._plan_locked(
                recorded_at=recorded_at,
                actor=actor,
                generator_version=generator_version,
            )

    @staticmethod
    def _validate_plan_digest(plan: dict[str, Any]) -> None:
        supplied = plan.get("plan_sha256")
        if not isinstance(supplied, str):
            raise ValueError("migration plan is missing plan_sha256")
        unsigned = {key: value for key, value in plan.items() if key != "plan_sha256"}
        if _sha256(_canonical_json(unsigned)) != supplied:
            raise ValueError("migration plan digest does not match its contents")

    def apply(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Apply a complete plan as one optimistic, atomic DAG transition."""

        self._validate_plan_digest(plan)
        if plan.get("schema_version") != MIGRATION_SCHEMA_VERSION:
            raise ValueError("unsupported legacy Intent IR migration schema")
        source = plan.get("source")
        if not isinstance(source, dict) or source.get("path") != INTENTION_DAG_FILE:
            raise ValueError(
                "migration plan does not target the canonical Intention DAG"
            )

        with dag_file_lock(self.dag_path):
            manager = self._manager()
            before_hash = self._dag_content_sha256(manager)
            if before_hash != source.get("sha256"):
                raise ValueError(
                    "stale migration plan: canonical Intention DAG has changed"
                )
            try:
                generated_at = datetime.fromisoformat(plan["generated_at"])
                actor = plan["actor"]
                generator_version = plan["generator_version"]
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    "migration plan compiler inputs are invalid"
                ) from error
            expected_plan = self._plan_locked(
                recorded_at=generated_at,
                actor=actor,
                generator_version=generator_version,
            )
            if plan != expected_plan:
                raise ValueError(
                    "migration plan does not match deterministic compiler output"
                )

            legacy = self._legacy_nodes(manager)
            items = plan.get("items")
            if not isinstance(items, list):
                raise ValueError("migration plan items must be a list")
            planned_ids = [
                item.get("node_id") for item in items if isinstance(item, dict)
            ]
            legacy_ids = [node.id for node in legacy]
            if planned_ids != legacy_ids:
                raise ValueError(
                    "migration plan must cover every legacy node in canonical order"
                )

            validated: list[tuple[Node, IntentIR]] = []
            for node, item in zip(legacy, items):
                if item.get("node_fingerprint") != self._node_fingerprint(
                    manager, node
                ):
                    raise ValueError(f"legacy node changed since planning: {node.id}")
                intent = IntentIR.model_validate(item.get("intent"))
                if intent.approval.state != ApprovalState.REVIEW_REQUIRED:
                    raise ValueError(
                        "mechanical migration cannot silently approve legacy intent"
                    )
                validated.append((node, intent))

            for node, intent in validated:
                manager.update_node(node.id, intent=intent)
            manager.validate_intent_ir(require_all=True)
            manager.save(str(guarded_dag_path(self.dag_path)))

            after_hash = self._dag_content_sha256(manager)
            return {
                "schema_version": MIGRATION_SCHEMA_VERSION,
                "plan_sha256": plan["plan_sha256"],
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "migrated_nodes": len(validated),
                "strict_validation": True,
                "approval_state": ApprovalState.REVIEW_REQUIRED.value,
            }
