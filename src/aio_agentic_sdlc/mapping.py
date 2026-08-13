"""Approval-gated promotion of fresh mapping evidence into Python source."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, field_validator

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_store import guarded_directory_path, guarded_file_path
from aio_agentic_sdlc.intent_ir import NonEmptyStr
from aio_agentic_sdlc.reality_dag_generator import (
    IGNORED_DIRECTORIES,
    RealityDAGGenerator,
)
from aio_agentic_sdlc.reconciliation import ReconciliationEngine
from aio_agentic_sdlc.source_markers import (
    MAPPING_APPROVAL_PREFIX,
    NODE_MARKER_PREFIX,
    iter_canonical_node_markers,
)
from aio_agentic_sdlc.workspace import (
    MAPPING_LOCK_FILE,
    require_current_workspace,
    workspace_file_path,
    workspace_migration_lock,
)

MAPPING_REVIEW_SCHEMA_VERSION = 2
MAPPING_APPROVAL_SCHEMA_VERSION = 1
SUPPORTED_SYMBOL_KINDS = {"class", "function"}
MAX_PUBLIC_API_ITEMS = 20
MAX_RELATED_TESTS = 10
MAX_INTENT_RELATIONSHIPS = 20
MAX_INTENT_DETAILS = 20


def _bounded(items: list[dict[str, Any]], maximum: int) -> dict[str, Any]:
    """Return deterministic bounded evidence while retaining complete totals."""

    total = len(items)
    returned = items[:maximum]
    return {
        "total": total,
        "returned": len(returned),
        "truncated": total > maximum,
        "items": returned,
    }


def _display_value(value: Any, fallback: str) -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _indented_text(value: Any, fallback: str, continuation: str = "    ") -> str:
    return _display_value(value, fallback).replace("\n", f"\n{continuation}")


def _human_provenance_reference(reference: str) -> str:
    if "#node:" in reference:
        return f"{reference.split('#', 1)[0]} (node statement)"
    if "#edge:" in reference:
        return f"{reference.split('#', 1)[0]} (relationship statement)"
    return reference


def _human_evidence_reference(reference: str) -> str:
    if reference.startswith("reconciliation:intent:"):
        return "fresh reconciliation evidence for this intent"
    return reference


def render_mapping_review(report: dict[str, Any]) -> str:
    """Render a mapping report as a human decision brief with audit data last."""

    brief = report["decision_brief"]
    intention = brief["intention"]
    implementation = brief.get("implementation")
    target_name = implementation["symbol"] if implementation else "no unique symbol"
    lines = [
        f"Mapping decision: {intention['title']} -> {target_name}",
        "",
        "What is intended",
        f"  Responsibility: {intention['responsibility']}",
        f"  Intent approval: {intention['approval_state']}",
        f"  Confidence: {intention['confidence']}",
    ]
    provenance = intention["provenance"]
    if provenance["items"]:
        lines.append("  Intent sources:")
        for item in provenance["items"]:
            lines.append(
                f"    - [{item['source_type']}] "
                f"{_human_provenance_reference(item['reference'])}: "
                f"{item['statement']}"
            )
        if provenance["truncated"]:
            lines.append(
                f"    - ... {provenance['total'] - provenance['returned']} more"
            )
    assumptions = intention["assumptions"]
    if assumptions["items"]:
        lines.append("  Assumptions:")
        lines.extend(f"    - {item['statement']}" for item in assumptions["items"])
        if assumptions["truncated"]:
            lines.append(
                f"    - ... {assumptions['total'] - assumptions['returned']} more"
            )
    criteria = intention["acceptance_criteria"]
    if criteria["items"]:
        lines.append("  Acceptance criteria (not verified by mapping):")
        for index, criterion in enumerate(criteria["items"], start=1):
            lines.append(f"    - Criterion {index}: {criterion['statement']}")
            evidence = ", ".join(
                _human_evidence_reference(item)
                for item in criterion["required_evidence"]
            )
            lines.append(f"      Required evidence: {evidence}")
        if criteria["truncated"]:
            lines.append(f"    - ... {criteria['total'] - criteria['returned']} more")
    else:
        lines.append("  Acceptance criteria: none recorded")

    relationships = intention["relationships"]
    if relationships["items"]:
        lines.append("  Intended relationships:")
        for relationship in relationships["items"]:
            description = relationship.get("description")
            suffix = f" - {description}" if description else ""
            lines.append(
                "    - "
                f"{relationship['direction']} {relationship['relationship']} "
                f"{relationship['other']}"
                f"{suffix}"
            )
        if relationships["truncated"]:
            lines.append(
                f"    - ... {relationships['total'] - relationships['returned']} more"
            )

    lines.extend(["", "What exists"])
    if implementation is None:
        lines.append("  No single supported Python source symbol was found.")
    else:
        lines.extend(
            [
                f"  Symbol: {implementation['signature']}",
                f"  Location: {implementation['location']}",
                "  Documentation: "
                f"{_indented_text(implementation['docstring'], 'none')}",
            ]
        )
        if implementation["bases"]:
            lines.append(f"  Bases: {', '.join(implementation['bases'])}")
        public_api = implementation["public_api"]
        if public_api["items"]:
            lines.append("  Public API:")
            for member in public_api["items"]:
                description = _display_value(member["docstring"], "no docstring")
                lines.append(f"    - {member['signature']} - {description}")
            if public_api["truncated"]:
                lines.append(
                    f"    - ... {public_api['total'] - public_api['returned']} more"
                )
        else:
            lines.append("  Public API: no public methods detected")

        related_tests = implementation["related_tests"]
        lines.append("  Related tests (references, not proof):")
        if related_tests["items"]:
            for test in related_tests["items"]:
                lines.append(f"    - {test['path']}:{test['line']} - {test['test']}")
            if related_tests["truncated"]:
                lines.append(
                    f"    - ... {related_tests['total'] - related_tests['returned']} more"
                )
        else:
            lines.append("    - none found by exact symbol reference")

    assessment = brief["assessment"]
    lines.extend(["", "What the tool established"])
    for statement in assessment["established"]:
        lines.append(f"  - {statement}")
    lines.append("")
    lines.append("What still needs human judgment")
    for statement in assessment["not_established"]:
        lines.append(f"  - {statement}")

    lines.extend(
        [
            "",
            "Decision choices",
            "  APPROVE - link this Intent GUID to this exact source symbol.",
            "  REJECT  - do not link; route the mismatch back to the Cartographer.",
            "  DEFER   - gather better intent or implementation evidence first.",
            "  Default: DEFER (structural matching alone is insufficient).",
            "",
            "Audit metadata (for approve command; not decision evidence)",
            f"  Intent GUID: {report['intent']['id']}",
            "  Candidate Reality GUID: "
            + (
                report["candidates"][0]["reality"]["id"]
                if len(report["candidates"]) == 1
                else "unavailable"
            ),
            f"  Evidence digest: {report['evidence_digest'] or 'unavailable'}",
        ]
    )
    if report["approval"]["blockers"]:
        lines.append("  Approval blockers:")
        lines.extend(f"    - {blocker}" for blocker in report["approval"]["blockers"])
    return "\n".join(lines)


class MappingError(ValueError):
    """Raised when mapping evidence cannot be safely approved."""


class MappingApproval(BaseModel):
    """Explicit human approval fields stored in the source receipt."""

    model_config = ConfigDict(extra="forbid")

    approved_by: NonEmptyStr
    approved_at: datetime
    rationale: NonEmptyStr

    @field_validator("approved_at")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("mapping approval approved_at must be timezone-aware")
        return value


# aio-sdlc-node: 6317643a-a8fc-5026-b373-9330004bc90d
class MappingEngine:
    """Review and approve one exact, fresh structural mapping candidate."""

    def __init__(self, project_root: str | Path, intention_path: str | Path):
        self.project_root = Path(project_root).resolve()
        candidate_intention = Path(intention_path)
        if not candidate_intention.is_absolute():
            candidate_intention = self.project_root / candidate_intention
        self.intention_path = candidate_intention.resolve()
        self._require_contained(self.intention_path, label="Intention DAG")

    def _require_contained(self, path: Path, *, label: str) -> Path:
        try:
            path.relative_to(self.project_root)
        except ValueError as error:
            raise MappingError(f"{label} escapes project root: {path}") from error
        return path

    @staticmethod
    def _canonical_guid(value: str, *, label: str) -> str:
        try:
            return str(UUID(value))
        except (ValueError, TypeError, AttributeError) as error:
            raise MappingError(f"{label} must be a canonical UUID") from error

    def _fresh_state(self):
        intention = DAGManager.load(str(self.intention_path))
        generator = RealityDAGGenerator(
            root_dir=str(self.project_root),
            system_name=intention.metadata.name,
        )
        reality = generator.generate()
        return intention, reality, generator

    def _intent_record(self, intent_id: str, intention, reality):
        canonical_intent_id = self._canonical_guid(intent_id, label="Intent GUID")
        for record in ReconciliationEngine(intention, reality).iter_intent_records(
            max_candidates=100
        ):
            if str(UUID(record["intent"]["id"])) == canonical_intent_id:
                return record
        raise MappingError(f"Intent node {canonical_intent_id} does not exist")

    def _intent_node(self, intent_id: str, intention):
        canonical_intent_id = self._canonical_guid(intent_id, label="Intent GUID")
        for node in intention.nodes.values():
            if str(UUID(node.id)) == canonical_intent_id:
                return node
        raise MappingError(f"Intent node {canonical_intent_id} does not exist")

    def _source_path(self, relative_path: str) -> Path:
        lexical_path = self.project_root / Path(relative_path)
        resolved_path = lexical_path.resolve()
        self._require_contained(resolved_path, label="Mapping source")
        try:
            return guarded_file_path(lexical_path)
        except ValueError as error:
            raise MappingError(
                f"unsafe mapping source: {relative_path}: {error}"
            ) from error

    @staticmethod
    def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
        arguments = ast.unparse(node.args)
        returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"{prefix}{node.name}({arguments}){returns}"

    @staticmethod
    def _definition_node(tree: ast.AST, source: dict[str, Any]):
        expected_types = (
            (ast.ClassDef,)
            if source["symbol_kind"] == "class"
            else (ast.FunctionDef, ast.AsyncFunctionDef)
        )
        matches = [
            node
            for node in ast.walk(tree)
            if isinstance(node, expected_types)
            and node.name == source["symbol_name"]
            and node.lineno == source["definition_line"]
        ]
        if len(matches) != 1:
            raise MappingError(
                "candidate source no longer resolves to one exact Python definition"
            )
        return matches[0]

    @staticmethod
    def _test_functions(tree: ast.Module):
        def walk(nodes, prefix=""):
            for node in nodes:
                if isinstance(node, ast.ClassDef):
                    yield from walk(node.body, f"{prefix}{node.name}.")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("test"):
                        yield f"{prefix}{node.name}", node

        yield from walk(tree.body)

    @staticmethod
    def _references_symbol(node: ast.AST, symbol_name: str) -> bool:
        return any(
            (isinstance(child, ast.Name) and child.id == symbol_name)
            or (isinstance(child, ast.Attribute) and child.attr == symbol_name)
            for child in ast.walk(node)
        )

    def _related_tests(self, symbol_name: str) -> dict[str, Any]:
        tests_root = self.project_root / "tests"
        if not tests_root.exists():
            return _bounded([], MAX_RELATED_TESTS)
        try:
            tests_root = guarded_directory_path(tests_root)
        except ValueError as error:
            raise MappingError(f"unsafe tests directory: {error}") from error

        matches: list[dict[str, Any]] = []
        total_matches = 0
        for root, directories, filenames in os.walk(tests_root):
            try:
                current = guarded_directory_path(root)
                safe_directories = []
                for directory in sorted(directories):
                    if directory in IGNORED_DIRECTORIES:
                        continue
                    guarded_directory_path(current / directory)
                    safe_directories.append(directory)
                directories[:] = safe_directories
            except ValueError as error:
                raise MappingError(f"unsafe tests directory: {error}") from error

            for filename in sorted(filenames):
                if not filename.endswith(".py"):
                    continue
                try:
                    test_path = guarded_file_path(current / filename)
                    raw_source = test_path.read_bytes()
                    parsed = ast.parse(
                        raw_source.decode("utf-8"), filename=str(test_path)
                    )
                except UnicodeDecodeError:
                    continue
                except SyntaxError:
                    continue
                except ValueError as error:
                    raise MappingError(f"unsafe test source: {error}") from error

                relative = test_path.relative_to(self.project_root).as_posix()
                source_sha256 = hashlib.sha256(raw_source).hexdigest()
                for test_name, test_node in self._test_functions(parsed):
                    if self._references_symbol(test_node, symbol_name):
                        total_matches += 1
                        if len(matches) < MAX_RELATED_TESTS:
                            matches.append(
                                {
                                    "path": relative,
                                    "line": test_node.lineno,
                                    "test": test_name,
                                    "match": "exact_symbol_reference",
                                    "source_sha256": source_sha256,
                                }
                            )

        return {
            "total": total_matches,
            "returned": len(matches),
            "truncated": total_matches > len(matches),
            "items": matches,
        }

    def _implementation_summary(self, source: dict[str, Any]) -> dict[str, Any]:
        source_path = self._source_path(source["path"])
        try:
            content = source_path.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(source_path))
        except (UnicodeDecodeError, SyntaxError) as error:
            raise MappingError(
                f"candidate Python source cannot be inspected: {error}"
            ) from error
        definition = self._definition_node(tree, source)
        decorators = [ast.unparse(item) for item in definition.decorator_list]
        bases: list[str] = []
        public_members: list[dict[str, Any]] = []
        public_member_total = 0
        if isinstance(definition, ast.ClassDef):
            bases = [ast.unparse(base) for base in definition.bases]
            signature = f"class {definition.name}"
            if bases:
                signature += f"({', '.join(bases)})"
            for member in definition.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and not (
                    member.name.startswith("_")
                ):
                    public_member_total += 1
                    if len(public_members) < MAX_PUBLIC_API_ITEMS:
                        public_members.append(
                            {
                                "name": member.name,
                                "signature": self._function_signature(member),
                                "line": member.lineno,
                                "docstring": ast.get_docstring(member, clean=True),
                            }
                        )
        else:
            signature = self._function_signature(definition)

        return {
            "symbol": source["symbol_name"],
            "kind": source["symbol_kind"],
            "signature": signature,
            "location": f"{source['path']}:{source['definition_line']}",
            "docstring": ast.get_docstring(definition, clean=True),
            "bases": bases,
            "decorators": decorators,
            "public_api": {
                "total": public_member_total,
                "returned": len(public_members),
                "truncated": public_member_total > len(public_members),
                "items": public_members,
            },
            "related_tests": self._related_tests(source["symbol_name"]),
        }

    def _intent_relationships(self, intention, intent_id: str) -> dict[str, Any]:
        canonical_id = str(UUID(intent_id))
        nodes = {str(UUID(node.id)): node for node in intention.nodes.values()}
        relationships = []
        for edge in intention.edges:
            source_id = str(UUID(edge.source))
            target_id = str(UUID(edge.target))
            if source_id == canonical_id:
                direction = "outgoing"
                other_id = target_id
            elif target_id == canonical_id:
                direction = "incoming"
                other_id = source_id
            else:
                continue
            other = nodes.get(other_id)
            relationships.append(
                {
                    "direction": direction,
                    "relationship": edge.type.value,
                    "other": other.name if other else "unknown node",
                    "description": edge.description,
                }
            )
        relationships.sort(
            key=lambda item: (
                item["direction"],
                item["relationship"],
                item["other"].casefold(),
                item["description"] or "",
            )
        )
        return _bounded(relationships, MAX_INTENT_RELATIONSHIPS)

    def _intent_summary(self, intention, intent_id: str) -> dict[str, Any]:
        node = self._intent_node(intent_id, intention)
        intent = node.intent
        acceptance_criteria = []
        provenance = []
        assumptions = []
        open_ambiguities = []
        confidence: float | str = "not recorded"
        approval_state = "not recorded"
        if intent is not None:
            acceptance_criteria = [
                {
                    "id": criterion.id,
                    "statement": criterion.statement,
                    "required_evidence": list(criterion.required_evidence),
                    "mapping_review_status": "not_verified",
                }
                for criterion in intent.acceptance_criteria
            ]
            provenance = [item.model_dump(mode="json") for item in intent.provenance]
            assumptions = list(intent.assumptions)
            open_ambiguities = [
                ambiguity.question
                for ambiguity in intent.ambiguities
                if ambiguity.status.value == "open"
            ]
            confidence = intent.confidence
            approval_state = intent.approval.state.value
        return {
            "title": node.name,
            "type": node.type.value,
            "domain": node.domain,
            "responsibility": _display_value(
                node.description, "No responsibility statement recorded."
            ),
            "approval_state": approval_state,
            "confidence": confidence,
            "acceptance_criteria": _bounded(acceptance_criteria, MAX_INTENT_DETAILS),
            "provenance": _bounded(provenance, MAX_INTENT_DETAILS),
            "assumptions": _bounded(
                [{"statement": item} for item in assumptions], MAX_INTENT_DETAILS
            ),
            "open_ambiguities": _bounded(
                [{"question": item} for item in open_ambiguities],
                MAX_INTENT_DETAILS,
            ),
            "relationships": self._intent_relationships(intention, node.id),
        }

    def _candidate_summary(self, candidate, generator):
        locations = generator.source_locations.get(candidate["id"], [])
        source_locations = []
        for location in locations:
            source_path = self._source_path(location.path)
            current_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
            source = location.as_dict()
            if current_hash != source["source_sha256"]:
                raise MappingError(
                    f"source changed during mapping review: {location.path}"
                )
            source_locations.append(source)

        summary: dict[str, Any] = {
            "reality": candidate,
            "source_location_count": len(source_locations),
        }
        if len(source_locations) == 1:
            summary["source"] = source_locations[0]
        elif source_locations:
            summary["source_locations"] = source_locations
        return summary

    def _decision_brief(
        self,
        intention,
        record: dict[str, Any],
        candidates: list[dict[str, Any]],
        *,
        supported: bool,
    ) -> dict[str, Any]:
        intent_summary = self._intent_summary(intention, record["intent"]["id"])
        implementation = (
            self._implementation_summary(candidates[0]["source"]) if supported else None
        )
        established = []
        if record["classification"] == "candidate":
            established.append(
                "The Intention title and Reality symbol have the same normalized name "
                "and compatible structural type."
            )
        else:
            established.append(
                f"Reconciliation classified this intent as {record['classification']}."
            )
        if implementation is not None:
            established.append(
                "Exactly one current Python definition resolves to the candidate source "
                f"at {implementation['location']}."
            )
            if implementation["related_tests"]["total"]:
                established.append(
                    f"{implementation['related_tests']['total']} test function(s) contain "
                    "an exact reference to the symbol."
                )

        not_established = [
            "Whether the source symbol has the same responsibility as the Intention node.",
            "Whether related tests exercise the acceptance criteria; references are not "
            "behavioral proof.",
        ]
        not_established.extend(
            "Acceptance criterion "
            f"{index} is not behaviorally verified by this mapping review."
            for index, _criterion in enumerate(
                intent_summary["acceptance_criteria"]["items"], start=1
            )
        )
        not_established.extend(
            f"Open Intent ambiguity: {item['question']}"
            for item in intent_summary["open_ambiguities"]["items"]
        )
        if intent_summary["acceptance_criteria"]["truncated"]:
            not_established.append(
                "Additional acceptance criteria were omitted from the bounded brief and "
                "remain unverified."
            )
        if intent_summary["open_ambiguities"]["truncated"]:
            not_established.append(
                "Additional open ambiguities were omitted from the bounded brief."
            )
        return {
            "decision_scope": "source_identity_linkage",
            "default_decision": "defer",
            "meaning": (
                "Approval links one canonical Intent GUID to one exact source symbol. "
                "It does not approve the Intent IR or prove acceptance criteria."
            ),
            "intention": intent_summary,
            "implementation": implementation,
            "assessment": {
                "summary": (
                    "Structural evidence narrows the candidate, but human judgment is "
                    "required to decide responsibility equivalence."
                ),
                "structurally_unique": supported,
                "behaviorally_verified": False,
                "established": established,
                "not_established": not_established,
            },
        }

    @staticmethod
    def _evidence_digest(payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def review(self, intent_id: str) -> dict[str, Any]:
        """Return fresh source-bound evidence without mutating project state."""

        intention, reality, generator = self._fresh_state()
        record = self._intent_record(intent_id, intention, reality)
        candidates = [
            self._candidate_summary(candidate, generator)
            for candidate in record["reality_candidates"]
        ]

        blockers = []
        if record["classification"] != "candidate":
            blockers.append(
                f"classification is {record['classification']}, not a unique candidate"
            )
        if len(candidates) != 1:
            blockers.append("mapping approval requires exactly one Reality candidate")
        elif candidates[0]["source_location_count"] != 1:
            blockers.append("candidate does not resolve to exactly one source location")
        elif candidates[0]["source"]["symbol_kind"] not in SUPPORTED_SYMBOL_KINDS:
            blockers.append(
                "candidate source kind is not supported by the Python definition adapter"
            )

        supported = not blockers
        decision_brief = self._decision_brief(
            intention,
            record,
            candidates,
            supported=supported,
        )
        report: dict[str, Any] = {
            "schema_version": MAPPING_REVIEW_SCHEMA_VERSION,
            "classification": record["classification"],
            "intent": record["intent"],
            "candidates": candidates,
            "evidence": record["evidence"],
            "decision_brief": decision_brief,
            "approval": {
                "required": True,
                "supported": supported,
                "blockers": blockers,
            },
            "evidence_digest": None,
        }
        if supported:
            report["evidence_digest"] = self._evidence_digest(
                {
                    "schema_version": MAPPING_REVIEW_SCHEMA_VERSION,
                    "classification": record["classification"],
                    "intent": record["intent"],
                    "intent_semantics": self._intent_node(
                        record["intent"]["id"], intention
                    ).model_dump(mode="json"),
                    "candidate": candidates[0],
                    "evidence": record["evidence"],
                    "decision_brief": decision_brief,
                }
            )
        return report

    def _iter_python_files(self):
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = sorted(
                directory for directory in dirs if directory not in IGNORED_DIRECTORIES
            )
            for filename in sorted(files):
                if filename.endswith(".py"):
                    yield Path(root) / filename

    def _reject_existing_marker(self, intent_id: str) -> None:
        for source_path in self._iter_python_files():
            try:
                content = source_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if intent_id in iter_canonical_node_markers(content):
                relative = source_path.relative_to(self.project_root).as_posix()
                raise MappingError(
                    f"canonical Intent GUID already appears in source: {relative}"
                )

    @staticmethod
    def _atomic_replace_bytes(target: Path, content: bytes, *, mode: int) -> None:
        descriptor, temporary = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, mode)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _mapped_source(original: bytes, source: dict[str, Any], receipt: dict) -> bytes:
        try:
            content = original.decode("utf-8")
        except UnicodeDecodeError as error:
            raise MappingError("mapping source must be UTF-8") from error
        lines = content.splitlines(keepends=True)
        insertion_index = source["marker_line"] - 1
        if insertion_index < 0 or insertion_index >= len(lines):
            raise MappingError("mapping source marker line is outside the source file")

        target_line = lines[insertion_index]
        indentation = target_line[: len(target_line) - len(target_line.lstrip())]
        newline = "\r\n" if "\r\n" in content else "\n"
        receipt_json = json.dumps(
            receipt,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        insertion = [
            f"{indentation}# {MAPPING_APPROVAL_PREFIX} {receipt_json}{newline}",
            f"{indentation}# {NODE_MARKER_PREFIX} {receipt['intent_id']}{newline}",
        ]
        return "".join(
            [*lines[:insertion_index], *insertion, *lines[insertion_index:]]
        ).encode("utf-8")

    def _verify_mapping(
        self,
        intent_id: str,
        *,
        source_path: str,
        symbol_name: str,
    ) -> dict[str, Any]:
        intention, reality, generator = self._fresh_state()
        record = self._intent_record(intent_id, intention, reality)
        if record["classification"] != "confirmed":
            raise MappingError(
                "post-write Reality verification did not confirm the canonical GUID"
            )
        locations = generator.source_locations.get(intent_id, [])
        if not any(
            location.path == source_path and location.symbol_name == symbol_name
            for location in locations
        ):
            raise MappingError(
                "post-write Reality verification confirmed the wrong source symbol"
            )
        return {
            "classification": "confirmed",
            "reality": record["reality_candidates"][0],
            "source": next(
                location.as_dict()
                for location in locations
                if location.path == source_path and location.symbol_name == symbol_name
            ),
        }

    def approve(
        self,
        intent_id: str,
        reality_id: str,
        evidence_digest: str,
        approval: MappingApproval,
    ) -> dict[str, Any]:
        """Atomically persist one approved candidate as verified source evidence."""

        canonical_intent_id = self._canonical_guid(intent_id, label="Intent GUID")
        lock_path = workspace_file_path(self.project_root, MAPPING_LOCK_FILE)
        with (
            workspace_migration_lock(self.project_root),
            FileLock(lock_path, timeout=10),
        ):
            require_current_workspace(self.project_root)
            review = self.review(canonical_intent_id)
            if not review["approval"]["supported"]:
                raise MappingError("mapping approval requires one unique candidate")

            candidate = review["candidates"][0]
            current_reality_id = candidate["reality"]["id"]
            try:
                requested_reality_id = str(UUID(reality_id))
            except (ValueError, TypeError, AttributeError) as error:
                raise MappingError(
                    "approved candidate Reality GUID does not match fresh evidence"
                ) from error
            if requested_reality_id != str(UUID(current_reality_id)):
                raise MappingError(
                    "approved candidate Reality GUID does not match fresh evidence"
                )
            if evidence_digest != review["evidence_digest"]:
                raise MappingError("stale mapping evidence digest")

            source = candidate["source"]
            source_path = self._source_path(source["path"])
            original = source_path.read_bytes()
            if hashlib.sha256(original).hexdigest() != source["source_sha256"]:
                raise MappingError("stale mapping evidence source hash")
            self._reject_existing_marker(canonical_intent_id)

            receipt = {
                "schema_version": MAPPING_APPROVAL_SCHEMA_VERSION,
                "intent_id": canonical_intent_id,
                "candidate_reality_id": str(UUID(current_reality_id)),
                "source_path": source["path"],
                "symbol_kind": source["symbol_kind"],
                "symbol_name": source["symbol_name"],
                "source_sha256": source["source_sha256"],
                "evidence_digest": review["evidence_digest"],
                "approved_by": approval.approved_by,
                "approved_at": approval.approved_at.isoformat(),
                "rationale": approval.rationale,
            }
            mode = stat.S_IMODE(source_path.stat().st_mode)
            mapped = self._mapped_source(original, source, receipt)
            self._atomic_replace_bytes(source_path, mapped, mode=mode)
            try:
                postcondition = self._verify_mapping(
                    canonical_intent_id,
                    source_path=source["path"],
                    symbol_name=source["symbol_name"],
                )
            except Exception:
                self._atomic_replace_bytes(source_path, original, mode=mode)
                raise

            return {
                "schema_version": MAPPING_APPROVAL_SCHEMA_VERSION,
                "receipt": receipt,
                "postcondition": postcondition,
            }
