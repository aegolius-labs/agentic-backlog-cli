"""Canonical source-marker parsing shared by Reality and mapping workflows."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tokenize
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

NODE_MARKER_PREFIX = "aio-sdlc-node:"
MAPPING_APPROVAL_PREFIX = "aio-sdlc-mapping-approval:"
MAX_MAPPING_RECEIPT_BYTES = 16 * 1024
NODE_MARKER_PATTERN = re.compile(
    r"^[ \t]*#\s*aio-sdlc-node:\s*([a-fA-F0-9-]+)\s*$",
    re.MULTILINE,
)
MAPPING_APPROVAL_PATTERN = re.compile(
    rb"^(?P<indent>[ \t]*)#\s*aio-sdlc-mapping-approval:\s*"
    rb"(?P<payload>\{.*\})[ \t]*(?P<newline>\r?\n)?$"
)
MAPPING_APPROVAL_CANDIDATE_PATTERN = re.compile(
    rb"^[ \t]*#\s*aio-sdlc-mapping-approval:"
)
_DIGEST_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_SCHEMA_ONE_FIELDS = {
    "schema_version",
    "intent_id",
    "candidate_reality_id",
    "source_path",
    "symbol_kind",
    "symbol_name",
    "source_sha256",
    "evidence_digest",
    "approved_by",
    "approved_at",
    "rationale",
}
_SCHEMA_TWO_FIELDS = {
    "schema_version",
    "intent_id",
    "candidate_reality_id",
    "source_path",
    "symbol_kind",
    "symbol_name",
    "source_sha256",
    "identity_approval",
    "maintenance_approval",
}
_MAINTENANCE_APPROVAL_FIELDS = {
    "evidence_digest",
    "approved_by",
    "approved_at",
    "rationale",
    "supersedes_receipt_sha256",
}


class SourceMarkerError(ValueError):
    """Raised when a source identity annotation is malformed or ambiguous."""


@dataclass(frozen=True)
class MappingReceiptAnnotation:
    """One validated adjacent receipt-marker pair and its neutral source bytes."""

    receipt: dict[str, Any]
    receipt_sha256: str
    annotation_neutral_bytes: bytes
    receipt_line: int
    marker_line: int


def _canonical_guid(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise SourceMarkerError(f"mapping receipt {label} must be a canonical UUID")
    try:
        canonical = str(UUID(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise SourceMarkerError(
            f"mapping receipt {label} must be a canonical UUID"
        ) from error
    if value != canonical:
        raise SourceMarkerError(f"mapping receipt {label} must be a canonical UUID")
    return canonical


def _require_digest(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
        raise SourceMarkerError(f"mapping receipt {label} must be a SHA-256 digest")
    return value


def _require_text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceMarkerError(f"mapping receipt {label} must be non-empty text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise SourceMarkerError(
            f"mapping receipt {label} must contain only Unicode scalar values"
        ) from error
    return value


def _require_timestamp(value: Any, *, label: str) -> str:
    text = _require_text(value, label=label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise SourceMarkerError(
            f"mapping receipt {label} must be a valid ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SourceMarkerError(f"mapping receipt {label} must be timezone-aware")
    return text


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SourceMarkerError(f"duplicate mapping receipt JSON key: {key}")
        result[key] = value
    return result


def _receipt_comment_line_indexes(content: bytes) -> list[int]:
    """Return zero-based lines for real Python receipt-comment tokens only."""

    try:
        tokens = tokenize.tokenize(io.BytesIO(content).readline)
        return [
            token.start[0] - 1
            for token in tokens
            if token.type == tokenize.COMMENT
            and MAPPING_APPROVAL_CANDIDATE_PATTERN.match(token.string.encode("utf-8"))
        ]
    except (
        IndentationError,
        SyntaxError,
        UnicodeDecodeError,
        tokenize.TokenError,
    ) as error:
        raise SourceMarkerError(
            "mapping source cannot be tokenized for receipt comments"
        ) from error


def _validate_schema_one(receipt: dict[str, Any]) -> dict[str, Any]:
    if set(receipt) != _SCHEMA_ONE_FIELDS:
        raise SourceMarkerError("mapping receipt schema 1 has an unknown field shape")
    if receipt.get("schema_version") != 1:
        raise SourceMarkerError("mapping receipt schema_version must be 1 or 2")
    _canonical_guid(receipt["intent_id"], label="intent_id")
    _canonical_guid(receipt["candidate_reality_id"], label="candidate_reality_id")
    _require_text(receipt["source_path"], label="source_path")
    if receipt["symbol_kind"] not in {"class", "function"}:
        raise SourceMarkerError("mapping receipt symbol_kind must be class or function")
    _require_text(receipt["symbol_name"], label="symbol_name")
    _require_digest(receipt["source_sha256"], label="source_sha256")
    _require_digest(receipt["evidence_digest"], label="evidence_digest")
    _require_text(receipt["approved_by"], label="approved_by")
    _require_timestamp(receipt["approved_at"], label="approved_at")
    _require_text(receipt["rationale"], label="rationale")
    return receipt


def _validate_schema_two(receipt: dict[str, Any]) -> dict[str, Any]:
    if set(receipt) != _SCHEMA_TWO_FIELDS:
        raise SourceMarkerError("mapping receipt schema 2 has an unknown field shape")
    if receipt.get("schema_version") != 2:
        raise SourceMarkerError("mapping receipt schema_version must be 1 or 2")
    _canonical_guid(receipt["intent_id"], label="intent_id")
    _canonical_guid(receipt["candidate_reality_id"], label="candidate_reality_id")
    _require_text(receipt["source_path"], label="source_path")
    if receipt["symbol_kind"] not in {"class", "function"}:
        raise SourceMarkerError("mapping receipt symbol_kind must be class or function")
    _require_text(receipt["symbol_name"], label="symbol_name")
    _require_digest(receipt["source_sha256"], label="source_sha256")
    identity = receipt["identity_approval"]
    if not isinstance(identity, dict):
        raise SourceMarkerError("mapping receipt identity_approval must be an object")
    _validate_schema_one(identity)
    maintenance = receipt["maintenance_approval"]
    if not isinstance(maintenance, dict) or set(maintenance) != (
        _MAINTENANCE_APPROVAL_FIELDS
    ):
        raise SourceMarkerError(
            "mapping receipt maintenance_approval has an unknown field shape"
        )
    _require_digest(maintenance["evidence_digest"], label="evidence_digest")
    _require_text(maintenance["approved_by"], label="approved_by")
    _require_timestamp(maintenance["approved_at"], label="approved_at")
    _require_text(maintenance["rationale"], label="rationale")
    _require_digest(
        maintenance["supersedes_receipt_sha256"],
        label="supersedes_receipt_sha256",
    )
    stable_fields = (
        "intent_id",
        "candidate_reality_id",
        "source_path",
        "symbol_kind",
        "symbol_name",
    )
    if any(receipt[field] != identity[field] for field in stable_fields):
        raise SourceMarkerError(
            "mapping receipt identity_approval does not match stable identity fields"
        )
    return receipt


def parse_mapping_receipt_annotation(
    content: bytes,
    *,
    intent_id: str,
    source_path: str,
    symbol_kind: str,
    symbol_name: str,
    marker_line: int,
) -> MappingReceiptAnnotation:
    """Validate one exact receipt-marker pair and return annotation-neutral bytes."""

    canonical_intent_id = _canonical_guid(intent_id, label="intent_id")
    lines = content.splitlines(keepends=True)
    receipt_lines = _receipt_comment_line_indexes(content)
    if len(receipt_lines) != 1:
        qualifier = "duplicate" if len(receipt_lines) > 1 else "missing"
        raise SourceMarkerError(f"{qualifier} mapping approval receipt")
    receipt_index = receipt_lines[0]
    marker_index = marker_line - 1
    if marker_index <= 0 or receipt_index + 1 != marker_index:
        raise SourceMarkerError(
            "mapping approval receipt must be immediately adjacent to its marker"
        )
    if marker_index >= len(lines):
        raise SourceMarkerError("mapping marker line is outside the source file")

    receipt_line = lines[receipt_index]
    if len(receipt_line) > MAX_MAPPING_RECEIPT_BYTES:
        raise SourceMarkerError("mapping approval receipt exceeds the size limit")
    match = MAPPING_APPROVAL_PATTERN.fullmatch(receipt_line)
    if match is None:
        raise SourceMarkerError("mapping approval receipt comment is malformed")
    try:
        receipt = json.loads(
            match.group("payload").decode("utf-8"),
            object_pairs_hook=_strict_object,
        )
    except UnicodeDecodeError as error:
        raise SourceMarkerError("mapping approval receipt must be UTF-8") from error
    except json.JSONDecodeError as error:
        raise SourceMarkerError("mapping approval receipt JSON is malformed") from error
    if not isinstance(receipt, dict):
        raise SourceMarkerError("mapping approval receipt must be a JSON object")
    schema_version = receipt.get("schema_version")
    if schema_version == 1:
        _validate_schema_one(receipt)
    elif schema_version == 2:
        _validate_schema_two(receipt)
    else:
        raise SourceMarkerError("mapping receipt schema_version must be 1 or 2")

    try:
        marker_text = lines[marker_index].decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise SourceMarkerError("mapping marker must be UTF-8") from error
    marker_guid = canonical_node_marker(marker_text)
    if marker_guid != canonical_intent_id:
        raise SourceMarkerError("mapping receipt marker does not match the Intent GUID")
    marker_indent = lines[marker_index][
        : len(lines[marker_index]) - len(lines[marker_index].lstrip())
    ]
    if match.group("indent") != marker_indent:
        raise SourceMarkerError("mapping receipt indentation does not match its marker")

    expected = {
        "intent_id": canonical_intent_id,
        "source_path": source_path,
        "symbol_kind": symbol_kind,
        "symbol_name": symbol_name,
    }
    for field, value in expected.items():
        if receipt[field] != value:
            raise SourceMarkerError(
                f"mapping receipt {field} does not match the symbol"
            )

    try:
        canonical_receipt = json.dumps(
            receipt,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    except UnicodeEncodeError as error:
        raise SourceMarkerError(
            "mapping receipt must contain only Unicode scalar values"
        ) from error
    neutral = b"".join(
        line
        for index, line in enumerate(lines)
        if index not in {receipt_index, marker_index}
    )
    return MappingReceiptAnnotation(
        receipt=receipt,
        receipt_sha256=hashlib.sha256(canonical_receipt).hexdigest(),
        annotation_neutral_bytes=neutral,
        receipt_line=receipt_index + 1,
        marker_line=marker_index + 1,
    )


def canonical_node_marker(line: str) -> str | None:
    """Return a canonical UUID only when the entire comment is a valid marker."""

    match = NODE_MARKER_PATTERN.fullmatch(line.rstrip("\r\n"))
    if not match:
        return None
    try:
        return str(UUID(match.group(1)))
    except ValueError:
        return None


def iter_canonical_node_markers(content: str):
    """Return canonical UUIDs from actual Python comment tokens only."""

    try:
        tokens = tokenize.generate_tokens(io.StringIO(content).readline)
        markers = []
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            marker = canonical_node_marker(token.string)
            if marker is not None:
                markers.append(marker)
        return iter(markers)
    except (IndentationError, SyntaxError, tokenize.TokenError) as error:
        raise SourceMarkerError(
            "mapping source cannot be tokenized for canonical markers"
        ) from error
