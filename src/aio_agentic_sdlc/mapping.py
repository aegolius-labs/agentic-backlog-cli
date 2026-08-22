"""Approval-gated promotion of fresh mapping evidence into Python source."""

from __future__ import annotations

import ast
import ctypes
import errno
import hashlib
import json
import os
import stat
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, field_validator

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_store import (
    dag_file_lock,
    guarded_directory_path,
    guarded_file_path,
)
from aio_agentic_sdlc.intent_ir import NonEmptyStr
from aio_agentic_sdlc.reality_dag_generator import (
    RealityDAGGenerator,
    is_ignored_directory,
)
from aio_agentic_sdlc.reconciliation import ReconciliationEngine
from aio_agentic_sdlc.source_markers import (
    MAPPING_APPROVAL_PREFIX,
    NODE_MARKER_PREFIX,
    MappingReceiptAnnotation,
    SourceMarkerError,
    iter_canonical_node_markers,
    parse_mapping_receipt_annotation,
)
from aio_agentic_sdlc.workspace import (
    MAPPING_LOCK_FILE,
    require_current_workspace,
    workspace_file_path,
    workspace_migration_lock,
)

MAPPING_REVIEW_SCHEMA_VERSION = 3
MAPPING_APPROVAL_SCHEMA_VERSION = 1
MAPPING_RECEIPT_SCHEMA_VERSION = 2
SUPPORTED_SYMBOL_KINDS = {"class", "function"}
SELECTION_MODES = {"automatic_name_match", "explicit_observed_guid"}
MAX_PUBLIC_API_ITEMS = 20
MAX_RELATED_TESTS = 10
MAX_INTENT_RELATIONSHIPS = 20
MAX_INTENT_DETAILS = 20
MAX_APPROVAL_TEXT_CHARS = 1024
MAX_DISPLAY_STRING_CHARS = 256
MAX_NESTED_DISPLAY_ITEMS = 20
DISPLAY_TRUNCATION_SUFFIX = "…[truncated]"


@dataclass(frozen=True)
class _SourceSnapshot:
    path: Path
    content: bytes
    mode: int
    identity: tuple[int, int]
    sha256: str


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


def _bounded_display_text(value: Any, fallback: str | None = None):
    """Return one safe bounded display string and explicit truncation metadata."""

    if value is None or value == "":
        value = fallback
    if value is None:
        return None, None
    original = str(value)
    scalar = "".join(
        "\ufffd" if 0xD800 <= ord(character) <= 0xDFFF else character
        for character in original
    )
    invalid_unicode_replaced = scalar != original
    truncated = len(scalar) > MAX_DISPLAY_STRING_CHARS
    if truncated:
        retained = MAX_DISPLAY_STRING_CHARS - len(DISPLAY_TRUNCATION_SUFFIX)
        rendered = scalar[:retained] + DISPLAY_TRUNCATION_SUFFIX
    else:
        rendered = scalar
    if not truncated and not invalid_unicode_replaced:
        return rendered, None
    metadata = {
        "truncated": truncated,
        "original_chars": len(original),
        "returned_chars": len(rendered),
        "limit_chars": MAX_DISPLAY_STRING_CHARS,
    }
    if invalid_unicode_replaced:
        metadata["invalid_unicode_replaced"] = True
    return rendered, metadata


def _bound_display_fields(
    payload: dict[str, Any],
    fields: tuple[str, ...],
    *,
    fallbacks: dict[str, str] | None = None,
) -> dict[str, Any]:
    result = dict(payload)
    bounds: dict[str, Any] = dict(result.get("_display_bounds", {}))
    for field in fields:
        if field not in result:
            continue
        rendered, metadata = _bounded_display_text(
            result[field],
            (fallbacks or {}).get(field),
        )
        result[field] = rendered
        if metadata is not None:
            bounds[field] = metadata
    if bounds:
        result["_display_bounds"] = bounds
    return result


def _bound_display_list(values: list[Any], *, maximum: int = MAX_NESTED_DISPLAY_ITEMS):
    total = len(values)
    rendered = []
    bounds = {}
    for index, value in enumerate(values[:maximum]):
        text, metadata = _bounded_display_text(value)
        rendered.append(text)
        if metadata is not None:
            bounds[str(index)] = metadata
    limit = None
    if total > len(rendered):
        limit = {
            "total": total,
            "returned": len(rendered),
            "truncated": True,
        }
    return rendered, bounds, limit


def _public_node_summary(node: dict[str, Any]) -> dict[str, Any]:
    """Bound node display fields while preserving the exact audit GUID."""

    return _bound_display_fields(dict(node), ("type", "name"))


def _public_source_summary(source: dict[str, Any]) -> dict[str, Any]:
    """Bound operational source labels while preserving coordinates and hashes."""

    return _bound_display_fields(
        dict(source),
        ("path", "symbol_kind", "symbol_name"),
    )


def _public_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exact_fields = {
        "id",
        "intent_source_id",
        "reality_source_id",
    }
    public = []
    for item in items[:MAX_NESTED_DISPLAY_ITEMS]:
        display_fields = tuple(
            key
            for key, value in item.items()
            if isinstance(value, str)
            and key not in exact_fields
            and not key.endswith(("_id", "_sha256", "_digest"))
        )
        public.append(_bound_display_fields(dict(item), display_fields))
    return public


def _public_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    result = _bound_display_fields(
        dict(receipt),
        ("source_path", "symbol_kind", "symbol_name"),
    )
    if receipt["schema_version"] == 1:
        return _bound_display_fields(
            result,
            ("approved_by", "approved_at", "rationale"),
        )
    result["identity_approval"] = _public_receipt(receipt["identity_approval"])
    result["maintenance_approval"] = _bound_display_fields(
        dict(receipt["maintenance_approval"]),
        ("approved_by", "approved_at", "rationale"),
    )
    return result


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


def render_receipt_refresh_review(report: dict[str, Any]) -> str:
    """Render receipt maintenance evidence with GUIDs and digests only at the end."""

    brief = report["decision_brief"]
    intention = brief["intention"]
    implementation = brief["implementation"]
    receipt = report["prior_receipt"]["data"]
    lines = [
        f"Receipt maintenance decision: {intention['title']} -> "
        f"{implementation['symbol']}",
        "",
        "What is preserved",
        "  The existing canonical source marker and original identity approval.",
        f"  Symbol: {implementation['signature']}",
        f"  Location: {implementation['location']}",
        f"  Existing receipt schema: {receipt['schema_version']}",
        "",
        "What is refreshed",
        "  Current annotation-neutral whole-file source evidence.",
        "  One bounded maintenance approval that supersedes the prior receipt.",
        "",
        "What the tool established",
    ]
    lines.extend(f"  - {item}" for item in brief["assessment"]["established"])
    lines.extend(["", "What this does not establish"])
    lines.extend(f"  - {item}" for item in brief["assessment"]["not_established"])
    lines.extend(
        [
            "",
            "Decision choices",
            "  APPROVE - refresh only the adjacent maintenance receipt.",
            "  REJECT  - preserve the existing marker and receipt unchanged.",
            "  DEFER   - gather better identity evidence first.",
            "  Default: DEFER (receipt freshness is not behavioral proof).",
            "",
            "Audit metadata (for refresh command; not decision evidence)",
            f"  Intent GUID: {report['intent']['id']}",
            f"  Confirmed Reality GUID: {report['candidates'][0]['reality']['id']}",
            f"  Prior receipt digest: {report['prior_receipt']['sha256']}",
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

    @field_validator("approved_by", "rationale")
    @classmethod
    def bound_audit_text(cls, value: str) -> str:
        if len(value) > MAX_APPROVAL_TEXT_CHARS:
            raise MappingError(
                f"mapping approval text must be at most {MAX_APPROVAL_TEXT_CHARS} "
                "characters"
            )
        try:
            value.encode("utf-8")
        except UnicodeEncodeError as error:
            raise MappingError(
                "mapping approval text must contain only Unicode scalar values"
            ) from error
        return value

    @field_validator("approved_at")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise MappingError("mapping approval approved_at must be timezone-aware")
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

    @contextmanager
    def _mapping_lock(self) -> Iterator[None]:
        """Acquire the persistent migration-then-mapping lock order."""

        with workspace_migration_lock(self.project_root):
            require_current_workspace(self.project_root)
            with dag_file_lock(self.intention_path):
                lock_path = workspace_file_path(self.project_root, MAPPING_LOCK_FILE)
                with FileLock(lock_path, timeout=10, preserve_lock_file=True):
                    require_current_workspace(self.project_root)
                    yield

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

    @staticmethod
    def _stat_identity(value: os.stat_result) -> tuple[int, int]:
        return value.st_dev, value.st_ino

    def _source_snapshot(self, path: Path) -> _SourceSnapshot:
        try:
            source_path = guarded_file_path(path)
            flags = (
                os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(source_path, flags)
        except (OSError, ValueError) as error:
            raise MappingError(
                "mapping source is not a guarded regular file"
            ) from error
        try:
            opened = os.fstat(descriptor)
            leaf = os.stat(source_path, follow_symlinks=False)
            if not stat.S_ISREG(opened.st_mode) or self._stat_identity(
                opened
            ) != self._stat_identity(leaf):
                raise MappingError("mapping source identity changed during inspection")
            if opened.st_nlink != 1 or leaf.st_nlink != 1:
                raise MappingError("mapping source hardlinks are not supported")
            chunks = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            content = b"".join(chunks)
            return _SourceSnapshot(
                path=source_path,
                content=content,
                mode=stat.S_IMODE(opened.st_mode),
                identity=self._stat_identity(opened),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        finally:
            os.close(descriptor)

    def _require_snapshot_identity(self, snapshot: _SourceSnapshot) -> None:
        try:
            current = os.stat(snapshot.path, follow_symlinks=False)
        except OSError as error:
            raise MappingError(
                "mapping source identity changed before replacement"
            ) from error
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or self._stat_identity(current) != snapshot.identity
        ):
            raise MappingError("mapping source identity changed before replacement")

    def _fresh_state(self):
        try:
            intention_path = guarded_file_path(self.intention_path)
            intention_bytes = intention_path.read_bytes()
            intention = DAGManager.load(str(intention_path))
        except (OSError, ValueError) as error:
            raise MappingError(
                "canonical Intention DAG could not be inspected"
            ) from error
        generator = RealityDAGGenerator(
            root_dir=str(self.project_root),
            system_name=intention.metadata.name,
        )
        try:
            for source_path in self._iter_python_files():
                self._source_snapshot(source_path)
            reality = generator.generate()
        except MappingError:
            raise
        except (OSError, ValueError) as error:
            raise MappingError(
                "fresh Reality evidence could not be generated"
            ) from error
        return (
            intention,
            reality,
            generator,
            hashlib.sha256(intention_bytes).hexdigest(),
        )

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
                    if is_ignored_directory(directory):
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
                                _bound_display_fields(
                                    {
                                        "path": relative,
                                        "line": test_node.lineno,
                                        "test": test_name,
                                        "match": "exact_symbol_reference",
                                        "source_sha256": source_sha256,
                                    },
                                    ("path", "test", "match"),
                                )
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
                            _bound_display_fields(
                                {
                                    "name": member.name,
                                    "signature": self._function_signature(member),
                                    "line": member.lineno,
                                    "docstring": ast.get_docstring(member, clean=True),
                                },
                                ("name", "signature", "docstring"),
                            )
                        )
        else:
            signature = self._function_signature(definition)

        bounded_bases, base_bounds, base_limit = _bound_display_list(bases)
        bounded_decorators, decorator_bounds, decorator_limit = _bound_display_list(
            decorators
        )
        summary = _bound_display_fields(
            {
                "symbol": source["symbol_name"],
                "kind": source["symbol_kind"],
                "signature": signature,
                "location": f"{source['path']}:{source['definition_line']}",
                "docstring": ast.get_docstring(definition, clean=True),
                "bases": bounded_bases,
                "decorators": bounded_decorators,
                "public_api": {
                    "total": public_member_total,
                    "returned": len(public_members),
                    "truncated": public_member_total > len(public_members),
                    "items": public_members,
                },
                "related_tests": self._related_tests(source["symbol_name"]),
            },
            ("symbol", "kind", "signature", "location", "docstring"),
        )
        display_bounds = summary.setdefault("_display_bounds", {})
        if base_bounds:
            display_bounds["bases"] = base_bounds
        if decorator_bounds:
            display_bounds["decorators"] = decorator_bounds
        if not display_bounds:
            summary.pop("_display_bounds")
        if base_limit is not None:
            summary["bases_limit"] = base_limit
        if decorator_limit is not None:
            summary["decorators_limit"] = decorator_limit
        return summary

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
                _bound_display_fields(
                    {
                        "direction": direction,
                        "relationship": edge.type.value,
                        "other": other.name if other else "unknown node",
                        "description": edge.description,
                    },
                    ("direction", "relationship", "other", "description"),
                )
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
            for criterion in intent.acceptance_criteria:
                evidence, evidence_bounds, evidence_limit = _bound_display_list(
                    list(criterion.required_evidence)
                )
                item = _bound_display_fields(
                    {
                        "id": criterion.id,
                        "statement": criterion.statement,
                        "required_evidence": evidence,
                        "mapping_review_status": "not_verified",
                    },
                    ("id", "statement", "mapping_review_status"),
                )
                if evidence_bounds:
                    item_bounds = item.setdefault("_display_bounds", {})
                    item_bounds["required_evidence"] = evidence_bounds
                if evidence_limit is not None:
                    item["required_evidence_limit"] = evidence_limit
                acceptance_criteria.append(item)
            provenance = [
                _bound_display_fields(
                    item.model_dump(mode="json"),
                    ("source_type", "reference", "statement"),
                )
                for item in intent.provenance
            ]
            assumptions = [
                _bound_display_fields({"statement": item}, ("statement",))
                for item in intent.assumptions
            ]
            open_ambiguities = [
                _bound_display_fields(
                    {"question": ambiguity.question},
                    ("question",),
                )
                for ambiguity in intent.ambiguities
                if ambiguity.status.value == "open"
            ]
            confidence = intent.confidence
            approval_state = intent.approval.state.value
        summary = _bound_display_fields(
            {
                "title": node.name,
                "type": node.type.value,
                "domain": node.domain,
                "responsibility": node.description,
                "approval_state": approval_state,
                "confidence": confidence,
                "acceptance_criteria": _bounded(
                    acceptance_criteria, MAX_INTENT_DETAILS
                ),
                "provenance": _bounded(provenance, MAX_INTENT_DETAILS),
                "assumptions": _bounded(assumptions, MAX_INTENT_DETAILS),
                "open_ambiguities": _bounded(
                    open_ambiguities,
                    MAX_INTENT_DETAILS,
                ),
                "relationships": self._intent_relationships(intention, node.id),
            },
            ("title", "type", "domain", "responsibility", "approval_state"),
            fallbacks={
                "responsibility": "No responsibility statement recorded.",
            },
        )
        return summary

    def _candidate_summary(self, candidate, generator):
        locations = generator.source_locations.get(candidate["id"], [])
        exact_source_locations = []
        for location in locations:
            source_path = self._source_path(location.path)
            snapshot = self._source_snapshot(source_path)
            source = location.as_dict()
            if snapshot.sha256 != source["source_sha256"]:
                raise MappingError(
                    f"source changed during mapping review: {location.path}"
                )
            source["raw_source_sha256"] = snapshot.sha256
            source["annotation_neutral_source_sha256"] = snapshot.sha256
            exact_source_locations.append(source)

        summary: dict[str, Any] = {
            "reality": _public_node_summary(candidate),
            "source_location_count": len(exact_source_locations),
        }
        if len(exact_source_locations) == 1:
            summary["source"] = _public_source_summary(exact_source_locations[0])
        elif exact_source_locations:
            summary["source_locations"] = [
                _public_source_summary(source)
                for source in exact_source_locations[:MAX_NESTED_DISPLAY_ITEMS]
            ]
            if len(exact_source_locations) > MAX_NESTED_DISPLAY_ITEMS:
                summary["source_locations_limit"] = {
                    "total": len(exact_source_locations),
                    "returned": MAX_NESTED_DISPLAY_ITEMS,
                    "truncated": True,
                }
        exact_summary: dict[str, Any] = {
            "reality": dict(candidate),
            "source_location_count": len(exact_source_locations),
        }
        if len(exact_source_locations) == 1:
            exact_summary["source"] = exact_source_locations[0]
        elif exact_source_locations:
            exact_summary["source_locations"] = exact_source_locations
        return summary, exact_summary

    def _decision_brief(
        self,
        intention,
        record: dict[str, Any],
        candidates: list[dict[str, Any]],
        exact_candidates: list[dict[str, Any]],
        *,
        supported: bool,
        selection_mode: str,
    ) -> dict[str, Any]:
        intent_summary = self._intent_summary(intention, record["intent"]["id"])
        implementation = (
            self._implementation_summary(exact_candidates[0]["source"])
            if supported
            else None
        )
        established = []
        if selection_mode == "explicit_observed_guid":
            established.append(
                "The reviewer explicitly selected one current Reality GUID; caller-"
                "supplied source metadata was not trusted."
            )
        elif record["classification"] == "candidate":
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
        bounded_established, established_bounds, established_limit = (
            _bound_display_list(established)
        )
        bounded_not_established, not_established_bounds, not_established_limit = (
            _bound_display_list(not_established)
        )
        assessment = {
            "summary": (
                "Structural evidence narrows the candidate, but human judgment is "
                "required to decide responsibility equivalence."
            ),
            "structurally_unique": supported,
            "behaviorally_verified": False,
            "established": bounded_established,
            "not_established": bounded_not_established,
        }
        if established_bounds or not_established_bounds:
            assessment["_display_bounds"] = {}
            if established_bounds:
                assessment["_display_bounds"]["established"] = established_bounds
            if not_established_bounds:
                assessment_bounds = assessment["_display_bounds"]
                assessment_bounds["not_established"] = not_established_bounds
        if established_limit is not None:
            assessment["established_limit"] = established_limit
        if not_established_limit is not None:
            assessment["not_established_limit"] = not_established_limit
        return {
            "decision_scope": "source_identity_linkage",
            "default_decision": "defer",
            "meaning": (
                "Approval links one canonical Intent GUID to one exact source symbol. "
                "It does not approve the Intent IR or prove acceptance criteria."
            ),
            "intention": intent_summary,
            "implementation": implementation,
            "assessment": assessment,
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

    def review(
        self,
        intent_id: str,
        *,
        candidate_reality_id: str | None = None,
    ) -> dict[str, Any]:
        """Return fresh source-bound evidence without mutating canonical state."""

        with self._mapping_lock():
            return self._review_locked(
                intent_id,
                candidate_reality_id=candidate_reality_id,
            )

    def _review_locked(
        self,
        intent_id: str,
        *,
        candidate_reality_id: str | None = None,
        include_context: bool = False,
    ):
        intention, reality, generator, intention_sha256 = self._fresh_state()
        record = self._intent_record(intent_id, intention, reality)
        selection_mode = (
            "explicit_observed_guid"
            if candidate_reality_id is not None
            else "automatic_name_match"
        )
        blockers: list[str] = []
        if candidate_reality_id is None:
            selected = record["reality_candidates"]
            if record["classification"] != "candidate":
                blockers.append(
                    f"classification is {record['classification']}, not a unique candidate"
                )
        else:
            selected_id = self._canonical_guid(
                candidate_reality_id,
                label="Observed Reality GUID",
            )
            matching = [
                node
                for node in reality.nodes.values()
                if str(UUID(node.id)) == selected_id
            ]
            if len(matching) != 1:
                raise MappingError(
                    "explicit observed Reality GUID does not resolve to one current node"
                )
            selected_node = matching[0]
            selected = [
                {
                    "id": str(UUID(selected_node.id)),
                    "type": selected_node.type.value,
                    "name": selected_node.name,
                }
            ]
            intent_node = self._intent_node(record["intent"]["id"], intention)
            if selected_node.type != intent_node.type:
                blockers.append(
                    "explicit candidate type is incompatible with the Intention node"
                )
            canonical_intention_ids = {
                str(UUID(node.id)) for node in intention.nodes.values()
            }
            if selected_id in canonical_intention_ids:
                blockers.append("explicit candidate is already confirmed to an Intent")

        candidate_pairs = [
            self._candidate_summary(candidate, generator) for candidate in selected
        ]
        candidates = [pair[0] for pair in candidate_pairs]
        exact_candidates = [pair[1] for pair in candidate_pairs]
        if len(candidates) != 1:
            blockers.append("mapping approval requires exactly one Reality candidate")
        elif exact_candidates[0]["source_location_count"] != 1:
            blockers.append("candidate does not resolve to exactly one source location")
        elif exact_candidates[0]["source"]["symbol_kind"] not in SUPPORTED_SYMBOL_KINDS:
            blockers.append(
                "candidate source kind is not supported by the Python definition adapter"
            )
        elif selection_mode == "explicit_observed_guid":
            source = exact_candidates[0]["source"]
            snapshot = self._source_snapshot(self._source_path(source["path"]))
            try:
                markers = set(
                    iter_canonical_node_markers(snapshot.content.decode("utf-8"))
                )
            except UnicodeDecodeError as error:
                raise MappingError("mapping source must be UTF-8") from error
            except SourceMarkerError as error:
                raise MappingError(str(error)) from error
            if exact_candidates[0]["reality"]["id"] in markers:
                blockers.append(
                    "explicit candidate already has a canonical source marker"
                )

        supported = not blockers
        decision_brief = self._decision_brief(
            intention,
            record,
            candidates,
            exact_candidates,
            supported=supported,
            selection_mode=selection_mode,
        )
        exact_evidence = list(record["evidence"])
        if selection_mode == "explicit_observed_guid":
            exact_evidence.append(
                {
                    "kind": "explicit_observed_guid",
                    "value": exact_candidates[0]["reality"]["id"],
                }
            )
        evidence = _public_evidence(exact_evidence)
        public_candidates = candidates[:MAX_NESTED_DISPLAY_ITEMS]
        report: dict[str, Any] = {
            "schema_version": MAPPING_REVIEW_SCHEMA_VERSION,
            "operation": "candidate_mapping",
            "selection_mode": selection_mode,
            "classification": record["classification"],
            "intent": _public_node_summary(record["intent"]),
            "candidates": public_candidates,
            "evidence": evidence,
            "decision_brief": decision_brief,
            "approval": {
                "required": True,
                "supported": supported,
                "blockers": blockers,
            },
            "evidence_digest": None,
        }
        if len(candidates) > len(public_candidates):
            report["candidates_limit"] = {
                "total": len(candidates),
                "returned": len(public_candidates),
                "truncated": True,
            }
        if len(exact_evidence) > len(evidence):
            report["evidence_limit"] = {
                "total": len(exact_evidence),
                "returned": len(evidence),
                "truncated": True,
            }
        if supported:
            report["evidence_digest"] = self._evidence_digest(
                {
                    "schema_version": MAPPING_REVIEW_SCHEMA_VERSION,
                    "operation": "candidate_mapping",
                    "selection_mode": selection_mode,
                    "canonical_intention_sha256": intention_sha256,
                    "classification": record["classification"],
                    "intent": record["intent"],
                    "intent_semantics": self._intent_node(
                        record["intent"]["id"], intention
                    ).model_dump(mode="json"),
                    "candidate": exact_candidates[0],
                    "evidence": exact_evidence,
                    "decision_brief": decision_brief,
                }
            )
        report["display_limits"] = {
            "max_string_chars": MAX_DISPLAY_STRING_CHARS,
            "max_nested_items": MAX_NESTED_DISPLAY_ITEMS,
        }
        if include_context:
            return report, {
                "candidate": exact_candidates[0] if exact_candidates else None,
            }
        return report

    def review_receipt_refresh(self, intent_id: str) -> dict[str, Any]:
        """Review fresh evidence for one already confirmed mapping receipt."""

        with self._mapping_lock():
            return self._review_receipt_refresh_locked(intent_id)

    def _review_receipt_refresh_locked(
        self,
        intent_id: str,
        *,
        include_context: bool = False,
    ):
        intention, reality, generator, intention_sha256 = self._fresh_state()
        record = self._intent_record(intent_id, intention, reality)
        if record["classification"] != "confirmed":
            raise MappingError("receipt refresh requires one confirmed source marker")
        candidate_pairs = [
            self._candidate_summary(candidate, generator)
            for candidate in record["reality_candidates"]
        ]
        candidates = [pair[0] for pair in candidate_pairs]
        exact_candidates = [pair[1] for pair in candidate_pairs]
        if len(candidates) != 1 or exact_candidates[0]["source_location_count"] != 1:
            raise MappingError(
                "receipt refresh requires exactly one confirmed source location"
            )
        source = exact_candidates[0]["source"]
        if source["symbol_kind"] not in SUPPORTED_SYMBOL_KINDS:
            raise MappingError(
                "receipt refresh supports only class or function symbols"
            )
        snapshot = self._source_snapshot(self._source_path(source["path"]))
        if snapshot.sha256 != source["source_sha256"]:
            raise MappingError("confirmed source changed during receipt review")
        try:
            annotation = parse_mapping_receipt_annotation(
                snapshot.content,
                intent_id=record["intent"]["id"],
                source_path=source["path"],
                symbol_kind=source["symbol_kind"],
                symbol_name=source["symbol_name"],
                marker_line=source["marker_line"],
            )
        except SourceMarkerError as error:
            raise MappingError(str(error)) from error
        neutral_sha256 = hashlib.sha256(annotation.annotation_neutral_bytes).hexdigest()
        source["raw_source_sha256"] = snapshot.sha256
        source["annotation_neutral_source_sha256"] = neutral_sha256
        source["raw_sha256"] = snapshot.sha256
        source["annotation_neutral_sha256"] = neutral_sha256
        candidates[0]["source"] = _public_source_summary(source)
        decision_brief = self._decision_brief(
            intention,
            record,
            candidates,
            exact_candidates,
            supported=True,
            selection_mode="confirmed_marker",
        )
        decision_brief["assessment"]["established"].append(
            "Exactly one complete adjacent mapping receipt matches the confirmed marker, "
            "path, kind, and symbol."
        )
        decision_brief["assessment"]["not_established"].append(
            "Receipt freshness does not prove behavior or acceptance criteria."
        )
        public_candidates = candidates[:MAX_NESTED_DISPLAY_ITEMS]
        exact_evidence = list(record["evidence"])
        public_evidence = _public_evidence(exact_evidence)
        report: dict[str, Any] = {
            "schema_version": MAPPING_REVIEW_SCHEMA_VERSION,
            "operation": "receipt_refresh",
            "selection_mode": "confirmed_marker",
            "classification": "confirmed",
            "intent": _public_node_summary(record["intent"]),
            "candidates": public_candidates,
            "source": _public_source_summary(
                {
                    **source,
                    "raw_sha256": snapshot.sha256,
                    "annotation_neutral_sha256": neutral_sha256,
                }
            ),
            "prior_receipt": {
                "sha256": annotation.receipt_sha256,
                "data": _public_receipt(annotation.receipt),
            },
            "evidence": public_evidence,
            "decision_brief": decision_brief,
            "approval": {"required": True, "supported": True, "blockers": []},
            "evidence_digest": None,
        }
        if len(candidates) > len(public_candidates):
            report["candidates_limit"] = {
                "total": len(candidates),
                "returned": len(public_candidates),
                "truncated": True,
            }
        if len(exact_evidence) > len(public_evidence):
            report["evidence_limit"] = {
                "total": len(exact_evidence),
                "returned": len(public_evidence),
                "truncated": True,
            }
        report["evidence_digest"] = self._evidence_digest(
            {
                "schema_version": MAPPING_REVIEW_SCHEMA_VERSION,
                "operation": "receipt_refresh",
                "selection_mode": "confirmed_marker",
                "canonical_intention_sha256": intention_sha256,
                "intent": record["intent"],
                "intent_semantics": self._intent_node(
                    record["intent"]["id"], intention
                ).model_dump(mode="json"),
                "candidate": exact_candidates[0],
                "source": source,
                "prior_receipt": {
                    "sha256": annotation.receipt_sha256,
                    "data": annotation.receipt,
                },
                "evidence": record["evidence"],
                "decision_brief": decision_brief,
            }
        )
        report["display_limits"] = {
            "max_string_chars": MAX_DISPLAY_STRING_CHARS,
            "max_nested_items": MAX_NESTED_DISPLAY_ITEMS,
        }
        if include_context:
            return report, {
                "source": source,
                "annotation": annotation,
            }
        return report

    def _iter_python_files(self):
        for root, dirs, files in os.walk(self.project_root):
            safe_directories = []
            for directory in sorted(dirs):
                if is_ignored_directory(directory):
                    continue
                candidate = Path(root) / directory
                try:
                    guarded_directory_path(candidate)
                except ValueError:
                    continue
                safe_directories.append(directory)
            dirs[:] = safe_directories
            for filename in sorted(files):
                if filename.endswith(".py"):
                    candidate = Path(root) / filename
                    self._require_contained(
                        candidate.resolve(),
                        label="Mapping source",
                    )
                    try:
                        yield guarded_file_path(candidate)
                    except ValueError as error:
                        raise MappingError(
                            "unsafe Python source encountered during marker scan"
                        ) from error

    def _reject_existing_marker(self, intent_id: str) -> None:
        for source_path in self._iter_python_files():
            try:
                content = self._source_snapshot(source_path).content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            try:
                markers = iter_canonical_node_markers(content)
            except SourceMarkerError as error:
                raise MappingError(str(error)) from error
            if intent_id in markers:
                relative = source_path.relative_to(self.project_root).as_posix()
                raise MappingError(
                    f"canonical Intent GUID already appears in source: {relative}"
                )

    @staticmethod
    def _write_source_temp(target: Path, content: bytes, *, mode: int) -> Path:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, mode)
            return temporary
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _open_bound_temporary(
        self,
        temporary: Path,
        *,
        expected: bytes,
        mode: int,
    ) -> tuple[int, tuple[int, int]]:
        """Open and retain one exact prepared leaf through source installation."""

        try:
            guarded_file_path(temporary)
            descriptor = os.open(
                temporary,
                os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
        except (OSError, ValueError) as error:
            raise MappingError(
                "mapping temporary is not a guarded regular file"
            ) from error
        try:
            opened = os.fstat(descriptor)
            leaf = os.stat(temporary, follow_symlinks=False)
            identity = self._stat_identity(opened)
            if (
                not stat.S_ISREG(opened.st_mode)
                or identity != self._stat_identity(leaf)
                or opened.st_nlink != 1
                or leaf.st_nlink != 1
                or stat.S_IMODE(opened.st_mode) != mode
            ):
                raise MappingError("mapping temporary identity is unsafe")
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 1024 * 1024):
                digest.update(chunk)
            os.lseek(descriptor, 0, os.SEEK_SET)
            if digest.hexdigest() != hashlib.sha256(expected).hexdigest():
                raise MappingError("mapping temporary content changed")
            return descriptor, identity
        except Exception:
            os.close(descriptor)
            raise

    def _require_temporary_identity(
        self,
        temporary: Path,
        identity: tuple[int, int],
    ) -> None:
        try:
            current = os.stat(temporary, follow_symlinks=False)
        except OSError as error:
            raise MappingError("mapping temporary identity changed") from error
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or self._stat_identity(current) != identity
        ):
            raise MappingError("mapping temporary identity changed")

    @staticmethod
    def _unique_reserved_leaf(target: Path, *, suffix: str) -> Path:
        descriptor, name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=suffix,
        )
        os.close(descriptor)
        reserved = Path(name)
        reserved.unlink()
        return reserved

    @staticmethod
    def _move_no_replace(source: Path, destination: Path) -> None:
        """Atomically move one leaf without replacing an occupied destination."""

        try:
            if os.name == "nt":
                # MoveFileEx without MOVEFILE_REPLACE_EXISTING is exposed by
                # ``os.rename`` on Windows and fails if the destination exists.
                os.rename(source, destination)
                return
            if sys.platform.startswith("linux"):
                libc = ctypes.CDLL(None, use_errno=True)
                try:
                    renameat2 = libc.renameat2
                except AttributeError as error:
                    raise MappingError(
                        "platform lacks an atomic no-overwrite source transition"
                    ) from error
                renameat2.argtypes = (
                    ctypes.c_int,
                    ctypes.c_char_p,
                    ctypes.c_int,
                    ctypes.c_char_p,
                    ctypes.c_uint,
                )
                renameat2.restype = ctypes.c_int
                result = renameat2(
                    -100,
                    os.fsencode(source),
                    -100,
                    os.fsencode(destination),
                    1,
                )
                if result != 0:
                    error_number = ctypes.get_errno()
                    raise OSError(
                        error_number,
                        os.strerror(error_number),
                        str(destination),
                    )
                return
            if sys.platform == "darwin":
                libc = ctypes.CDLL(None, use_errno=True)
                try:
                    renamex_np = libc.renamex_np
                except AttributeError as error:
                    raise MappingError(
                        "platform lacks an atomic no-overwrite source transition"
                    ) from error
                renamex_np.argtypes = (
                    ctypes.c_char_p,
                    ctypes.c_char_p,
                    ctypes.c_uint,
                )
                renamex_np.restype = ctypes.c_int
                result = renamex_np(
                    os.fsencode(source),
                    os.fsencode(destination),
                    0x00000004,
                )
                if result != 0:
                    error_number = ctypes.get_errno()
                    raise OSError(
                        error_number,
                        os.strerror(error_number),
                        str(destination),
                    )
                return
            raise MappingError(
                "platform lacks an atomic no-overwrite source transition"
            )
        except FileExistsError as error:
            raise MappingError("mapping private destination became occupied") from error
        except OSError as error:
            if error.errno in {errno.EEXIST, errno.ENOTEMPTY}:
                raise MappingError(
                    "mapping private destination became occupied"
                ) from error
            raise MappingError("mapping private move failed") from error

    def _quarantine_leaf(self, leaf: Path, target: Path) -> Path:
        quarantine = self._unique_reserved_leaf(
            target,
            suffix=".source-conflict",
        )
        self._move_no_replace(leaf, quarantine)
        return quarantine

    def _restore_snapshot_content_no_overwrite(
        self,
        snapshot: _SourceSnapshot,
    ) -> bool:
        if os.path.lexists(snapshot.path):
            return False
        temporary = self._write_source_temp(
            snapshot.path,
            snapshot.content,
            mode=snapshot.mode,
        )
        try:
            try:
                os.link(temporary, snapshot.path, follow_symlinks=False)
            except (FileExistsError, OSError):
                return False
            temporary.unlink()
            restored = self._source_snapshot(snapshot.path)
            return restored.sha256 == snapshot.sha256 and restored.mode == snapshot.mode
        finally:
            temporary.unlink(missing_ok=True)

    def _restore_backup_no_overwrite(
        self,
        snapshot: _SourceSnapshot,
        backup: Path,
    ) -> bool:
        try:
            backup_snapshot = self._source_snapshot(backup)
        except MappingError:
            return False
        if (
            backup_snapshot.identity != snapshot.identity
            or backup_snapshot.sha256 != snapshot.sha256
            or os.path.lexists(snapshot.path)
        ):
            return False
        try:
            os.link(backup, snapshot.path, follow_symlinks=False)
        except (FileExistsError, OSError):
            return False
        try:
            if backup_snapshot.mode & stat.S_IWUSR == 0:
                os.chmod(backup, backup_snapshot.mode | stat.S_IWUSR)
            os.unlink(backup)
            os.chmod(snapshot.path, snapshot.mode)
            restored = self._source_snapshot(snapshot.path)
            return (
                restored.identity == snapshot.identity
                and restored.sha256 == snapshot.sha256
                and restored.mode == snapshot.mode
            )
        except Exception:
            try:
                current = os.stat(snapshot.path, follow_symlinks=False)
                if self._stat_identity(current) == snapshot.identity:
                    os.unlink(snapshot.path)
            except OSError:
                pass
            return False

    @staticmethod
    def _is_link_like_leaf(path: Path) -> bool:
        try:
            leaf = os.lstat(path)
        except OSError:
            return False
        return stat.S_ISLNK(leaf.st_mode) or bool(
            getattr(leaf, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )

    def _remove_owned_install(
        self,
        path: Path,
        identity: tuple[int, int],
    ) -> bool:
        if not os.path.lexists(path):
            return True
        if self._is_link_like_leaf(path):
            return False
        try:
            current = os.stat(path, follow_symlinks=False)
        except OSError:
            return False
        if (
            not stat.S_ISREG(current.st_mode)
            or self._stat_identity(current) != identity
        ):
            return False
        try:
            if stat.S_IMODE(current.st_mode) & stat.S_IWUSR == 0:
                os.chmod(path, stat.S_IMODE(current.st_mode) | stat.S_IWUSR)
            os.unlink(path)
        except OSError:
            return False
        return True

    def _quarantine_unowned_source(self, source_path: Path) -> bool:
        """Preserve a swapped source leaf without following or overwriting it."""

        if not os.path.lexists(source_path):
            return True
        try:
            self._quarantine_leaf(source_path, source_path)
        except MappingError:
            return False
        return True

    def _transition_source(
        self,
        snapshot: _SourceSnapshot,
        updated: bytes,
        verify,
    ):
        """Install one prepared leaf without overwriting an unverified source path."""

        # Keep the private staging leaf writable until its extra link is removed.
        # Windows refuses to unlink a read-only leaf even when the installed source
        # is a second hard link to the same inode. The public source mode is restored
        # immediately after installation and before any semantic verification.
        requested_temporary_mode = snapshot.mode | stat.S_IWUSR
        temporary = self._write_source_temp(
            snapshot.path,
            updated,
            mode=requested_temporary_mode,
        )
        # chmod on Windows exposes only the read-only attribute and normalizes a
        # requested 0644 mode to 0666. Bind the actual staged mode rather than a
        # POSIX-only prediction; descriptor/leaf identity and content are still
        # checked together by ``_open_bound_temporary``.
        temporary_mode = stat.S_IMODE(os.stat(temporary, follow_symlinks=False).st_mode)
        backup = self._unique_reserved_leaf(
            snapshot.path,
            suffix=".source-backup",
        )
        temporary_descriptor: int | None = None
        backup_holds_expected = False
        temporary_identity: tuple[int, int] | None = None
        try:
            temporary_descriptor, temporary_identity = self._open_bound_temporary(
                temporary,
                expected=updated,
                mode=temporary_mode,
            )
            self._require_snapshot_identity(snapshot)
            try:
                self._require_temporary_identity(temporary, temporary_identity)
            except OSError as error:
                raise MappingError("mapping temporary identity changed") from error

            # The source is moved only to an absent unpredictable leaf. The native
            # primitive fails if another actor occupies that leaf first.
            self._move_no_replace(snapshot.path, backup)
            try:
                moved = self._source_snapshot(backup)
            except MappingError as error:
                self._quarantine_leaf(backup, snapshot.path)
                self._restore_snapshot_content_no_overwrite(snapshot)
                raise MappingError(
                    "mapping source identity changed; swapped leaf was quarantined"
                ) from error
            if (
                moved.identity != snapshot.identity
                or moved.sha256 != snapshot.sha256
                or moved.mode != snapshot.mode
            ):
                self._quarantine_leaf(backup, snapshot.path)
                self._restore_snapshot_content_no_overwrite(snapshot)
                raise MappingError(
                    "mapping source identity changed; swapped leaf was quarantined"
                )
            backup_holds_expected = True
            try:
                self._require_temporary_identity(temporary, temporary_identity)
            except OSError as error:
                raise MappingError("mapping temporary identity changed") from error
            try:
                os.link(temporary, snapshot.path, follow_symlinks=False)
            except (FileExistsError, OSError) as error:
                self._quarantine_leaf(backup, snapshot.path)
                backup_holds_expected = False
                raise MappingError(
                    "mapping source path became occupied; original was quarantined"
                ) from error

            try:
                installed_leaf = os.stat(snapshot.path, follow_symlinks=False)
                if (
                    not stat.S_ISREG(installed_leaf.st_mode)
                    or self._stat_identity(installed_leaf) != temporary_identity
                ):
                    raise MappingError("post-write source identity changed")
                os.close(temporary_descriptor)
                temporary_descriptor = None
                if not self._remove_owned_install(temporary, temporary_identity):
                    raise MappingError("mapping temporary identity changed")
                os.chmod(snapshot.path, snapshot.mode)
                written = self._source_snapshot(snapshot.path)
                if (
                    written.identity != temporary_identity
                    or written.sha256 != hashlib.sha256(updated).hexdigest()
                ):
                    raise MappingError("post-write source identity changed")
                postcondition = verify()
                final = self._source_snapshot(snapshot.path)
                if final.identity != written.identity or final.sha256 != written.sha256:
                    raise MappingError("post-write source identity changed")

                final_backup = self._source_snapshot(backup)
                if (
                    final_backup.identity != snapshot.identity
                    or final_backup.sha256 != snapshot.sha256
                ):
                    raise MappingError("mapping source backup identity changed")
                if final_backup.mode & stat.S_IWUSR == 0:
                    os.chmod(backup, final_backup.mode | stat.S_IWUSR)
                os.unlink(backup)
                backup_holds_expected = False
                final = self._source_snapshot(snapshot.path)
                if final.identity != temporary_identity:
                    raise MappingError("post-write source identity changed")
            except Exception as transition_error:
                removed_install = self._remove_owned_install(
                    snapshot.path,
                    temporary_identity,
                )
                if not removed_install:
                    removed_install = self._quarantine_unowned_source(snapshot.path)
                if removed_install and self._restore_backup_no_overwrite(
                    snapshot,
                    backup,
                ):
                    backup_holds_expected = False
                    raise transition_error
                if os.path.lexists(backup):
                    try:
                        self._quarantine_leaf(backup, snapshot.path)
                    except MappingError:
                        pass
                    else:
                        backup_holds_expected = False
                if removed_install and self._restore_snapshot_content_no_overwrite(
                    snapshot
                ):
                    raise transition_error
                raise MappingError(
                    "mapping transition failed; original source was quarantined"
                ) from transition_error
            return postcondition
        except Exception:
            if not os.path.lexists(snapshot.path):
                if backup_holds_expected and self._restore_backup_no_overwrite(
                    snapshot,
                    backup,
                ):
                    backup_holds_expected = False
                elif not backup_holds_expected:
                    self._restore_snapshot_content_no_overwrite(snapshot)
            if backup_holds_expected and os.path.lexists(backup):
                try:
                    self._quarantine_leaf(backup, snapshot.path)
                except MappingError:
                    pass
                else:
                    backup_holds_expected = False
            raise
        finally:
            if temporary_descriptor is not None:
                os.close(temporary_descriptor)
            if temporary_identity is not None:
                self._remove_owned_install(temporary, temporary_identity)
            if os.path.lexists(backup):
                if backup_holds_expected:
                    try:
                        self._quarantine_leaf(backup, snapshot.path)
                    except MappingError:
                        pass

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

    @staticmethod
    def _refreshed_source(
        original: bytes,
        annotation: MappingReceiptAnnotation,
        receipt: dict[str, Any],
    ) -> bytes:
        lines = original.splitlines(keepends=True)
        index = annotation.receipt_line - 1
        old_line = lines[index]
        indentation = old_line[: len(old_line) - len(old_line.lstrip())]
        newline = b"\r\n" if old_line.endswith(b"\r\n") else b"\n"
        receipt_json = json.dumps(
            receipt,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        lines[index] = (
            indentation
            + b"# "
            + MAPPING_APPROVAL_PREFIX.encode("utf-8")
            + b" "
            + receipt_json
            + newline
        )
        return b"".join(lines)

    def _verify_mapping(
        self,
        intent_id: str,
        *,
        source_path: str,
        symbol_name: str,
    ) -> dict[str, Any]:
        intention, reality, generator, _intention_sha256 = self._fresh_state()
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

    def _verify_candidate_receipt(
        self,
        intent_id: str,
        *,
        source_path: str,
        symbol_name: str,
        expected_receipt: dict[str, Any],
    ) -> dict[str, Any]:
        postcondition = self._verify_mapping(
            intent_id,
            source_path=source_path,
            symbol_name=symbol_name,
        )
        source = postcondition["source"]
        snapshot = self._source_snapshot(self._source_path(source_path))
        try:
            annotation = parse_mapping_receipt_annotation(
                snapshot.content,
                intent_id=intent_id,
                source_path=source_path,
                symbol_kind=source["symbol_kind"],
                symbol_name=symbol_name,
                marker_line=source["marker_line"],
            )
        except SourceMarkerError as error:
            raise MappingError(str(error)) from error
        if annotation.receipt != expected_receipt:
            raise MappingError("post-write mapping receipt does not match approval")
        return {
            **postcondition,
            "receipt_sha256": annotation.receipt_sha256,
        }

    def _verify_receipt_refresh(
        self,
        intent_id: str,
        *,
        source_path: str,
        symbol_name: str,
        evidence_digest: str,
    ) -> dict[str, Any]:
        postcondition = self._verify_mapping(
            intent_id,
            source_path=source_path,
            symbol_name=symbol_name,
        )
        source = postcondition["source"]
        snapshot = self._source_snapshot(self._source_path(source_path))
        try:
            annotation = parse_mapping_receipt_annotation(
                snapshot.content,
                intent_id=intent_id,
                source_path=source_path,
                symbol_kind=source["symbol_kind"],
                symbol_name=symbol_name,
                marker_line=source["marker_line"],
            )
        except SourceMarkerError as error:
            raise MappingError(str(error)) from error
        receipt = annotation.receipt
        if receipt["schema_version"] != MAPPING_RECEIPT_SCHEMA_VERSION:
            raise MappingError("post-write receipt verification found the wrong schema")
        if receipt["maintenance_approval"]["evidence_digest"] != evidence_digest:
            raise MappingError("post-write receipt verification found the wrong digest")
        return {
            **postcondition,
            "receipt_sha256": annotation.receipt_sha256,
        }

    def approve(
        self,
        intent_id: str,
        reality_id: str,
        evidence_digest: str,
        approval: MappingApproval,
        *,
        selection_mode: str = "automatic_name_match",
    ) -> dict[str, Any]:
        """Atomically persist one approved candidate as verified source evidence."""

        canonical_intent_id = self._canonical_guid(intent_id, label="Intent GUID")
        if selection_mode not in SELECTION_MODES:
            raise MappingError("mapping selection_mode is not supported")
        with self._mapping_lock():
            explicit_candidate = (
                reality_id if selection_mode == "explicit_observed_guid" else None
            )
            review, context = self._review_locked(
                canonical_intent_id,
                candidate_reality_id=explicit_candidate,
                include_context=True,
            )
            if not review["approval"]["supported"]:
                raise MappingError("mapping approval requires one unique candidate")

            candidate = context["candidate"]
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
            snapshot = self._source_snapshot(source_path)
            if snapshot.sha256 != source["source_sha256"]:
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
            mapped = self._mapped_source(snapshot.content, source, receipt)
            try:
                preflight = parse_mapping_receipt_annotation(
                    mapped,
                    intent_id=canonical_intent_id,
                    source_path=source["path"],
                    symbol_kind=source["symbol_kind"],
                    symbol_name=source["symbol_name"],
                    marker_line=source["marker_line"] + 1,
                )
            except SourceMarkerError as error:
                raise MappingError(str(error)) from error
            if (
                preflight.receipt != receipt
                or preflight.annotation_neutral_bytes != snapshot.content
            ):
                raise MappingError("mapping receipt preflight did not preserve source")
            postcondition = self._transition_source(
                snapshot,
                mapped,
                lambda: self._verify_candidate_receipt(
                    canonical_intent_id,
                    source_path=source["path"],
                    symbol_name=source["symbol_name"],
                    expected_receipt=receipt,
                ),
            )

            return {
                "schema_version": MAPPING_APPROVAL_SCHEMA_VERSION,
                "receipt": receipt,
                "postcondition": postcondition,
            }

    def refresh_receipt(
        self,
        intent_id: str,
        evidence_digest: str,
        approval: MappingApproval,
    ) -> dict[str, Any]:
        """Atomically replace one confirmed receipt from exact fresh evidence."""

        canonical_intent_id = self._canonical_guid(intent_id, label="Intent GUID")
        with self._mapping_lock():
            review, context = self._review_receipt_refresh_locked(
                canonical_intent_id,
                include_context=True,
            )
            if evidence_digest != review["evidence_digest"]:
                raise MappingError("stale receipt evidence digest")

            source = context["source"]
            source_path = self._source_path(source["path"])
            snapshot = self._source_snapshot(source_path)
            if snapshot.sha256 != source["raw_sha256"]:
                raise MappingError("stale receipt evidence source hash")
            try:
                annotation = parse_mapping_receipt_annotation(
                    snapshot.content,
                    intent_id=canonical_intent_id,
                    source_path=source["path"],
                    symbol_kind=source["symbol_kind"],
                    symbol_name=source["symbol_name"],
                    marker_line=source["marker_line"],
                )
            except SourceMarkerError as error:
                raise MappingError(str(error)) from error
            neutral_sha256 = hashlib.sha256(
                annotation.annotation_neutral_bytes
            ).hexdigest()
            if (
                annotation.receipt_sha256 != review["prior_receipt"]["sha256"]
                or neutral_sha256 != source["annotation_neutral_sha256"]
            ):
                raise MappingError("stale receipt evidence source hash")

            prior = annotation.receipt
            identity_approval = (
                prior if prior["schema_version"] == 1 else prior["identity_approval"]
            )
            receipt = {
                "schema_version": MAPPING_RECEIPT_SCHEMA_VERSION,
                "intent_id": prior["intent_id"],
                "candidate_reality_id": prior["candidate_reality_id"],
                "source_path": prior["source_path"],
                "symbol_kind": prior["symbol_kind"],
                "symbol_name": prior["symbol_name"],
                "source_sha256": neutral_sha256,
                "identity_approval": identity_approval,
                "maintenance_approval": {
                    "evidence_digest": review["evidence_digest"],
                    "approved_by": approval.approved_by,
                    "approved_at": approval.approved_at.isoformat(),
                    "rationale": approval.rationale,
                    "supersedes_receipt_sha256": annotation.receipt_sha256,
                },
            }
            refreshed = self._refreshed_source(snapshot.content, annotation, receipt)
            try:
                preflight = parse_mapping_receipt_annotation(
                    refreshed,
                    intent_id=canonical_intent_id,
                    source_path=source["path"],
                    symbol_kind=source["symbol_kind"],
                    symbol_name=source["symbol_name"],
                    marker_line=source["marker_line"],
                )
            except SourceMarkerError as error:
                raise MappingError(str(error)) from error
            if (
                preflight.receipt != receipt
                or preflight.annotation_neutral_bytes
                != annotation.annotation_neutral_bytes
            ):
                raise MappingError("mapping receipt preflight did not preserve source")
            postcondition = self._transition_source(
                snapshot,
                refreshed,
                lambda: self._verify_receipt_refresh(
                    canonical_intent_id,
                    source_path=source["path"],
                    symbol_name=source["symbol_name"],
                    evidence_digest=review["evidence_digest"],
                ),
            )
            return {
                "schema_version": MAPPING_RECEIPT_SCHEMA_VERSION,
                "receipt": receipt,
                "postcondition": postcondition,
            }
