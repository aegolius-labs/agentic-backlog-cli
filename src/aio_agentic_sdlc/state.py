"""Versioned, transactional persistence for the local execution backlog."""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
import tempfile
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from filelock import FileLock

from .workspace import (
    AUDIT_FILE,
    BACKLOG_FILE,
    LEGACY_DIR,
    STATE_LOCK_FILE,
    require_current_workspace,
    workspace_file_path,
    workspace_migration_lock,
)

LOCK_FILE = STATE_LOCK_FILE
CURRENT_BACKLOG_SCHEMA_VERSION = 1
LOCK_TIMEOUT_SECONDS = 30
MutationResultT = TypeVar("MutationResultT")


class BacklogStateError(ValueError):
    """Base error for invalid or unrecoverable local backlog state."""


class UnsupportedBacklogSchema(BacklogStateError):
    """Raised when a backlog was produced by a newer framework version."""


class BacklogRecoveryError(BacklogStateError):
    """Raised when an incomplete transaction cannot be reconciled safely."""


class BacklogConflictError(BacklogStateError):
    """Raised when a writer attempts to replace a newer backlog revision."""


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _file_sha256(file_path: str) -> str | None:
    if not os.path.exists(file_path):
        return None
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _append_audit_event(project_path: str, event: dict[str, Any]) -> None:
    audit_path = workspace_file_path(project_path, AUDIT_FILE)
    payload = (json.dumps(event, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    descriptor = os.open(audit_path, flags, 0o600)
    try:
        written = 0
        while written < len(payload):
            chunk_size = os.write(descriptor, payload[written:])
            if chunk_size == 0:
                raise OSError("Audit log write made no progress.")
            written += chunk_size
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_audit_events(project_path: str) -> list[dict[str, Any]]:
    audit_path = workspace_file_path(project_path, AUDIT_FILE)
    if not os.path.exists(audit_path):
        return []

    with open(audit_path, "rb") as handle:
        payload = handle.read()

    complete_length = payload.rfind(b"\n") + 1
    complete_payload = payload[:complete_length]
    truncated_bytes = len(payload) - complete_length
    repair_event = None
    if truncated_bytes:
        with open(audit_path, "r+b") as handle:
            handle.truncate(complete_length)
            handle.flush()
            os.fsync(handle.fileno())
        repair_event = {
            "operation": "audit.recover",
            "phase": "audit_tail_truncated",
            "timestamp": _utc_now(),
            "discarded_bytes": truncated_bytes,
        }
        _append_audit_event(project_path, repair_event)

    events = []
    for line_number, raw_line in enumerate(complete_payload.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BacklogRecoveryError(
                f"Invalid audit record at line {line_number}: {exc}"
            ) from exc
        if not isinstance(event, dict):
            raise BacklogRecoveryError(
                f"Invalid audit record at line {line_number}: expected an object."
            )
        events.append(event)
    if repair_event:
        events.append(repair_event)
    return events


def _state_lock(project_path: str) -> FileLock:
    lock_path = workspace_file_path(project_path, LOCK_FILE)
    return FileLock(
        lock_path,
        timeout=LOCK_TIMEOUT_SECONDS,
        preserve_lock_file=True,
    )


def _recover_incomplete_transactions(project_path: str) -> list[dict[str, str]]:
    events = _read_audit_events(project_path)
    prepared: dict[str, dict[str, Any]] = {}
    terminal_phases = {"committed", "rolled_back", "recovered_commit"}
    for event in events:
        transaction_id = event.get("transaction_id")
        if not transaction_id:
            continue
        if event.get("phase") == "prepared":
            prepared[transaction_id] = event
        elif event.get("phase") in terminal_phases:
            prepared.pop(transaction_id, None)

    if not prepared:
        return []

    backlog_path = workspace_file_path(project_path, BACKLOG_FILE)
    current_hash = _file_sha256(backlog_path)
    recovered = []
    for transaction_id, event in prepared.items():
        if current_hash == event.get("after_sha256"):
            phase = "recovered_commit"
        elif current_hash == event.get("before_sha256"):
            phase = "rolled_back"
        else:
            raise BacklogRecoveryError(
                "Backlog hash does not match either side of incomplete transaction "
                f"{transaction_id}; refusing to guess."
            )

        recovery_event = dict(event)
        recovery_event.update({"phase": phase, "timestamp": _utc_now()})
        _append_audit_event(project_path, recovery_event)
        recovered.append({"transaction_id": transaction_id, "phase": phase})

    return recovered


def recover_incomplete_transactions(project_path: str = ".") -> list[dict[str, str]]:
    """Reconcile prepared transactions against the current backlog hash."""

    with workspace_migration_lock(project_path):
        require_current_workspace(project_path)
        with _state_lock(project_path):
            return _recover_incomplete_transactions(project_path)


def _migrate_v0_to_v1(data: dict[str, Any]) -> dict[str, Any]:
    migrated = {
        key: copy.deepcopy(value)
        for key, value in data.items()
        if key not in {"schema_version", "items", "nodes", "edges"}
    }
    edges = copy.deepcopy(data.get("edges", []))

    if "nodes" in data:
        nodes = copy.deepcopy(data["nodes"])
    else:
        items = data.get("items", {})
        if not isinstance(items, dict):
            raise BacklogStateError("Legacy backlog 'items' must be an object.")
        nodes = {}
        for name, item in items.items():
            if not isinstance(item, dict):
                raise BacklogStateError(
                    f"Legacy backlog item '{name}' must be an object."
                )
            node = copy.deepcopy(item)
            node.setdefault("item_type", "Task")
            for requirement in node.pop("requires", []):
                edges.append({"from": name, "to": requirement, "relation": "requires"})
            parent_id = node.pop("parent_id", None)
            if parent_id:
                edges.append({"from": name, "to": parent_id, "relation": "parent"})
            nodes[name] = node

    migrated.update(
        {
            "schema_version": 1,
            "revision": 0,
            "nodes": nodes,
            "edges": edges,
        }
    )
    return migrated


def migrate_backlog_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return a validated copy migrated to the current schema version."""

    if not isinstance(data, dict):
        raise BacklogStateError("Backlog root must be an object.")

    version = data.get("schema_version", 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise BacklogStateError(
            "Backlog schema_version must be a non-negative integer."
        )
    if version > CURRENT_BACKLOG_SCHEMA_VERSION:
        raise UnsupportedBacklogSchema(
            f"Backlog schema {version} is newer than supported schema "
            f"{CURRENT_BACKLOG_SCHEMA_VERSION}."
        )

    migrated = copy.deepcopy(data)
    while version < CURRENT_BACKLOG_SCHEMA_VERSION:
        if version == 0:
            migrated = _migrate_v0_to_v1(migrated)
        else:
            raise UnsupportedBacklogSchema(
                f"No migration is available from schema {version}."
            )
        version = migrated["schema_version"]

    if not isinstance(migrated.get("nodes"), dict):
        raise BacklogStateError("Backlog 'nodes' must be an object.")
    if not isinstance(migrated.get("edges"), list):
        raise BacklogStateError("Backlog 'edges' must be an array.")
    revision = migrated.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise BacklogStateError("Backlog 'revision' must be a non-negative integer.")
    return migrated


def load_backlog(project_path: str = ".") -> dict[str, Any]:
    with workspace_migration_lock(project_path):
        require_current_workspace(project_path)
        with _state_lock(project_path):
            _recover_incomplete_transactions(project_path)
            backlog_path = workspace_file_path(project_path, BACKLOG_FILE)
            if not os.path.exists(backlog_path):
                return migrate_backlog_data({})
            with open(backlog_path, "r", encoding="utf-8") as handle:
                return migrate_backlog_data(json.load(handle))


def mutate_backlog(
    project_path: str,
    *,
    operation: str,
    mutator: Callable[[dict[str, Any]], tuple[MutationResultT, bool]],
) -> MutationResultT:
    """Apply one read-modify-write transaction while holding both state locks.

    The callback returns ``(result, changed)``. A false ``changed`` value preserves
    read-only/no-op behavior without incrementing the backlog revision.
    """

    with workspace_migration_lock(project_path):
        require_current_workspace(project_path)
        with _state_lock(project_path):
            _recover_incomplete_transactions(project_path)
            backlog_path = workspace_file_path(project_path, BACKLOG_FILE)
            if os.path.exists(backlog_path):
                with open(backlog_path, "r", encoding="utf-8") as handle:
                    data = migrate_backlog_data(json.load(handle))
            else:
                data = migrate_backlog_data({})

            result, changed = mutator(data)
            if changed:
                _save_backlog_unlocked(data, project_path, operation=operation)
            return result


def save_backlog(
    data: dict[str, Any],
    project_path: str = ".",
    *,
    operation: str = "backlog.save",
) -> None:
    """Atomically replace backlog state with a recoverable audit transaction."""

    with workspace_migration_lock(project_path):
        require_current_workspace(project_path)
        with _state_lock(project_path):
            _save_backlog_unlocked(data, project_path, operation=operation)


def _save_backlog_unlocked(
    data: dict[str, Any], project_path: str, *, operation: str
) -> None:
    _recover_incomplete_transactions(project_path)
    normalized = migrate_backlog_data(data)
    backlog_path = workspace_file_path(project_path, BACKLOG_FILE)
    backlog_dir = os.path.dirname(backlog_path)
    os.makedirs(backlog_dir, exist_ok=True)
    if os.path.exists(backlog_path):
        with open(backlog_path, "r", encoding="utf-8") as handle:
            current = migrate_backlog_data(json.load(handle))
        current_revision = current["revision"]
    else:
        current_revision = 0

    if normalized["revision"] != current_revision:
        raise BacklogConflictError(
            f"Backlog write used stale revision {normalized['revision']}; "
            f"current revision is {current_revision}. Reload before retrying."
        )

    normalized["revision"] = current_revision + 1
    payload = (json.dumps(normalized, indent=2) + "\n").encode("utf-8")
    before_hash = _file_sha256(backlog_path)
    after_hash = hashlib.sha256(payload).hexdigest()
    transaction_id = str(uuid.uuid4())
    base_event = {
        "transaction_id": transaction_id,
        "operation": operation,
        "schema_version": CURRENT_BACKLOG_SCHEMA_VERSION,
        "before_revision": current_revision,
        "after_revision": normalized["revision"],
        "before_sha256": before_hash,
        "after_sha256": after_hash,
    }

    descriptor, temp_path = tempfile.mkstemp(
        dir=backlog_dir,
        prefix=".backlog.json.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        prepared = dict(base_event)
        prepared.update({"phase": "prepared", "timestamp": _utc_now()})
        _append_audit_event(project_path, prepared)
        os.replace(temp_path, backlog_path)

        committed = dict(base_event)
        committed.update({"phase": "committed", "timestamp": _utc_now()})
        _append_audit_event(project_path, committed)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def migrate_backlog(project_path: str = ".") -> dict[str, int | bool]:
    """Persist an existing backlog using the current schema and audit contract."""

    with workspace_migration_lock(project_path):
        require_current_workspace(project_path)
        with _state_lock(project_path):
            _recover_incomplete_transactions(project_path)
            backlog_path = workspace_file_path(project_path, BACKLOG_FILE)
            if os.path.exists(backlog_path):
                with open(backlog_path, "r", encoding="utf-8") as handle:
                    raw = json.load(handle)
            else:
                raw = {}

            from_version = raw.get("schema_version", 0) if isinstance(raw, dict) else 0
            migrated = migrate_backlog_data(raw)
            changed = raw != migrated
            if changed:
                _save_backlog_unlocked(
                    migrated, project_path, operation="backlog.migrate"
                )
            return {
                "from_version": from_version,
                "to_version": CURRENT_BACKLOG_SCHEMA_VERSION,
                "changed": changed,
            }


def retire_legacy_backlog(
    project_path: str = ".",
) -> dict[str, bool | str | None]:
    """Archive and remove the obsolete generated `.agentic-backlog.json`."""

    with workspace_migration_lock(project_path):
        require_current_workspace(project_path)
        with _state_lock(project_path):
            return _retire_legacy_backlog_locked(project_path)


def _retire_legacy_backlog_locked(
    project_path: str,
) -> dict[str, bool | str | None]:
    """Retire the generated backlog while workspace and state locks are held."""

    legacy_path = os.path.join(project_path, ".agentic-backlog.json")
    if not os.path.lexists(legacy_path):
        return {"changed": False, "archive": None, "sha256": None}
    if os.path.islink(legacy_path) or not os.path.isfile(legacy_path):
        raise BacklogStateError(
            "Legacy backlog must be a regular file; refusing to follow a link."
        )

    with open(legacy_path, "rb") as handle:
        payload = handle.read()
    try:
        legacy_data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BacklogStateError(f"Legacy backlog is not valid JSON: {exc}") from exc
    if not isinstance(legacy_data, dict):
        raise BacklogStateError("Legacy backlog root must be an object.")

    digest = hashlib.sha256(payload).hexdigest()
    archive_relative = f"{LEGACY_DIR}/agentic-backlog-{digest}.json"
    archive_path = workspace_file_path(project_path, archive_relative)
    archive_dir = archive_path.parent

    if os.path.exists(archive_path):
        if _file_sha256(archive_path) != digest:
            raise BacklogStateError(
                "Legacy archive hash collision; refusing to replace existing data."
            )
    else:
        descriptor, temp_path = tempfile.mkstemp(
            dir=archive_dir,
            prefix=".agentic-backlog.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, archive_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    os.remove(legacy_path)
    _append_audit_event(
        project_path,
        {
            "operation": "legacy-backlog.retire",
            "phase": "committed",
            "timestamp": _utc_now(),
            "source": ".agentic-backlog.json",
            "archive": archive_relative,
            "sha256": digest,
        },
    )
    return {
        "changed": True,
        "archive": archive_relative,
        "sha256": digest,
    }
