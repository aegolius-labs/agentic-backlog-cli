"""Approval-gated promotion of fresh mapping evidence into Python source."""

from __future__ import annotations

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
from aio_agentic_sdlc.workspace import MAPPING_LOCK_FILE

MAPPING_SCHEMA_VERSION = 1
SUPPORTED_SYMBOL_KINDS = {"class", "function"}


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

    def _source_path(self, relative_path: str) -> Path:
        lexical_path = self.project_root / Path(relative_path)
        resolved_path = lexical_path.resolve()
        return self._require_contained(resolved_path, label="Mapping source")

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
        report: dict[str, Any] = {
            "schema_version": MAPPING_SCHEMA_VERSION,
            "classification": record["classification"],
            "intent": record["intent"],
            "candidates": candidates,
            "evidence": record["evidence"],
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
                    "schema_version": MAPPING_SCHEMA_VERSION,
                    "classification": record["classification"],
                    "intent": record["intent"],
                    "candidate": candidates[0],
                    "evidence": record["evidence"],
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
        lock_path = self.project_root / MAPPING_LOCK_FILE
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(lock_path, timeout=10):
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
                "schema_version": MAPPING_SCHEMA_VERSION,
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
                "schema_version": MAPPING_SCHEMA_VERSION,
                "receipt": receipt,
                "postcondition": postcondition,
            }
