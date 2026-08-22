"""Canonical project-local paths for AIO Agentic SDLC artifacts and state."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import yaml
from filelock import FileLock

WORKSPACE_DIR = ".aio-agentic-sdlc"

INTENTION_DAG_FILE = f"{WORKSPACE_DIR}/intention-dag.yaml"
REALITY_DAG_FILE = f"{WORKSPACE_DIR}/reality-dag.yaml"
BACKLOG_FILE = f"{WORKSPACE_DIR}/backlog.json"
CONFIG_FILE = f"{WORKSPACE_DIR}/config.json"
AUDIT_FILE = f"{WORKSPACE_DIR}/state-audit.jsonl"
STATE_LOCK_FILE = f"{WORKSPACE_DIR}/state.lock"
MAPPING_LOCK_FILE = f"{WORKSPACE_DIR}/mapping.lock"
WORKSPACE_MIGRATION_LOCK_FILE = f"{WORKSPACE_DIR}/workspace-migration.lock"
LEGACY_DIR = f"{WORKSPACE_DIR}/legacy"

INBOX_DIR = f"{WORKSPACE_DIR}/inbox"
SPECS_DIR = f"{WORKSPACE_DIR}/specs"
CHANGES_DIR = f"{WORKSPACE_DIR}/changes"
ARCHIVE_DIR = f"{WORKSPACE_DIR}/archive"
RESEARCH_SPIKES_DIR = f"{WORKSPACE_DIR}/research-spikes"

OPERATIONAL_DIRECTORIES = (
    INBOX_DIR,
    SPECS_DIR,
    CHANGES_DIR,
    ARCHIVE_DIR,
    RESEARCH_SPIKES_DIR,
)

LEGACY_PATHS = {
    "backlog.json": BACKLOG_FILE,
    ".aio-agentic-sdlc.json": CONFIG_FILE,
    "intention-dag.yaml": INTENTION_DAG_FILE,
    "reality-dag.yaml": REALITY_DAG_FILE,
    ".aio-sdlc/state-audit.jsonl": AUDIT_FILE,
    ".aio-sdlc/legacy": LEGACY_DIR,
}
LEGACY_DIRECTORY_PATHS = {".aio-sdlc/legacy"}


class WorkspaceMigrationError(RuntimeError):
    """Raised when legacy framework state cannot be migrated safely."""


class WorkspaceMigrationRequired(WorkspaceMigrationError):
    """Raised when a command would silently ignore a legacy workspace."""


class WorkspaceMigrationConflict(WorkspaceMigrationError):
    """Raised when both legacy and canonical paths contain state."""


def workspace_path(project_path: str | Path = ".", *parts: str) -> Path:
    """Return a path inside the canonical project-local framework workspace."""

    return Path(project_path) / WORKSPACE_DIR / Path(*parts)


def _validated_workspace_root(project_path: str | Path = ".") -> Path:
    root = workspace_path(project_path)
    if _lexists(root):
        if root.is_symlink() or not root.is_dir():
            raise WorkspaceMigrationError(
                "Canonical workspace must be a real directory, not a symlink or file."
            )
    else:
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise WorkspaceMigrationError(
                "Canonical workspace must be a real directory, not a symlink or file."
            )
    return root


def ensure_workspace(project_path: str | Path = ".") -> Path:
    """Create the canonical framework workspace and operational directories."""

    root = _validated_workspace_root(project_path)
    for relative in OPERATIONAL_DIRECTORIES:
        directory = Path(project_path) / relative
        if _lexists(directory):
            if directory.is_symlink() or not directory.is_dir():
                raise WorkspaceMigrationError(
                    f"Framework workspace path must be a real directory: {relative}."
                )
        else:
            directory.mkdir(parents=True, exist_ok=True)
            if directory.is_symlink() or not directory.is_dir():
                raise WorkspaceMigrationError(
                    f"Framework workspace path must be a real directory: {relative}."
                )
    return root


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def workspace_file_path(
    project_path: str | Path, relative_path: str, *, create_parent: bool = True
) -> Path:
    """Return a canonical workspace file path after rejecting link redirection."""

    workspace = _validated_workspace_root(project_path)
    candidate = Path(project_path) / relative_path
    try:
        relative = candidate.relative_to(workspace)
    except ValueError as exc:
        raise WorkspaceMigrationError(
            f"Workspace file escapes the canonical parent: {relative_path}."
        ) from exc

    current = workspace
    for part in relative.parts[:-1]:
        current /= part
        if _lexists(current):
            if current.is_symlink() or not current.is_dir():
                raise WorkspaceMigrationError(
                    f"Workspace parent must be a real directory: {current}."
                )
        elif create_parent:
            current.mkdir(exist_ok=True)
            if current.is_symlink() or not current.is_dir():
                raise WorkspaceMigrationError(
                    f"Workspace parent must be a real directory: {current}."
                )
        else:
            break

    if _lexists(candidate) and (candidate.is_symlink() or not candidate.is_file()):
        raise WorkspaceMigrationError(
            f"Workspace file must be a regular file: {relative_path}."
        )
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _normalized_legacy_config(source: Path) -> bytes:
    try:
        config = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceMigrationError(
            f"Legacy configuration is invalid: {exc}"
        ) from exc
    if not isinstance(config, dict):
        raise WorkspaceMigrationError("Legacy configuration root must be an object.")
    core = config.get("core", {})
    if not isinstance(core, dict):
        raise WorkspaceMigrationError("Legacy configuration 'core' must be an object.")
    config["core"] = {**core, "mode": "local"}
    config.pop("github", None)
    return (json.dumps(config, indent=2) + "\n").encode("utf-8")


def _validate_legacy_backlog(source: Path) -> None:
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceMigrationError(f"Legacy backlog is invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceMigrationError("Legacy backlog root must be an object.")
    has_items = isinstance(data.get("items"), dict)
    has_graph = isinstance(data.get("nodes"), dict) and isinstance(
        data.get("edges"), list
    )
    if not (has_items or has_graph):
        raise WorkspaceMigrationError(
            "Root backlog.json does not match an AIO backlog envelope; refusing to "
            "claim a potentially host-owned file."
        )
    version = data.get("schema_version", 0)
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise WorkspaceMigrationError(
            "Legacy backlog schema_version must be a non-negative integer."
        )


def _validate_legacy_dag(source: Path) -> None:
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise WorkspaceMigrationError(f"Legacy DAG is invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceMigrationError("Legacy DAG root must be an object.")
    if not isinstance(data.get("nodes"), list) or not isinstance(
        data.get("edges"), list
    ):
        raise WorkspaceMigrationError("Legacy DAG must contain node and edge arrays.")


def _normalized_legacy_audit(source: Path) -> bytes | None:
    payload = source.read_bytes()
    complete_length = payload.rfind(b"\n") + 1
    try:
        complete_text = payload[:complete_length].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceMigrationError(
            f"Complete legacy audit records are not UTF-8: {exc}"
        ) from exc
    for line_number, line in enumerate(complete_text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise WorkspaceMigrationError(
                f"Legacy audit record {line_number} is invalid JSON: {exc}"
            ) from exc
        if not isinstance(event, dict):
            raise WorkspaceMigrationError(
                f"Legacy audit record {line_number} must be an object."
            )

    tail = payload[complete_length:]
    if not tail:
        return None
    try:
        tail_event = json.loads(tail.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        recovery = {
            "operation": "audit.recover",
            "phase": "audit_tail_truncated",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "discarded_bytes": len(payload) - complete_length,
        }
        return payload[:complete_length] + (
            json.dumps(recovery, sort_keys=True) + "\n"
        ).encode("utf-8")
    if not isinstance(tail_event, dict):
        raise WorkspaceMigrationError("Legacy audit final record must be an object.")
    return None


def workspace_migration_lock(project_path: str | Path = ".") -> FileLock:
    """Return the cross-process lock that gates layout checks and migration."""

    lock_path = workspace_file_path(project_path, WORKSPACE_MIGRATION_LOCK_FILE)
    return FileLock(lock_path, timeout=30, preserve_lock_file=True)


def require_current_workspace(project_path: str | Path = ".") -> None:
    """Fail before normal commands can ignore state in a legacy layout."""

    root = Path(project_path)
    legacy = [source for source in LEGACY_PATHS if _lexists(root / source)]
    if legacy:
        joined = ", ".join(sorted(legacy))
        raise WorkspaceMigrationRequired(
            "Legacy AIO Agentic SDLC paths are present "
            f"({joined}); run `aio-sdlc migrate-state` before continuing."
        )


def migrate_legacy_workspace(project_path: str | Path = ".") -> dict[str, Any]:
    """Move known legacy artifacts into the canonical workspace, or fail closed."""

    root = Path(project_path)
    _validated_workspace_root(root)

    with workspace_migration_lock(root):
        legacy_state_dir = root / ".aio-sdlc"
        if _lexists(legacy_state_dir) and legacy_state_dir.is_symlink():
            raise WorkspaceMigrationError(
                "Legacy state directory must not be a symlink."
            )

        bridge_paths = [
            legacy_state_dir / "state.lock",
            legacy_state_dir / "mapping.lock",
        ]
        bridge_existed = {path: _lexists(path) for path in bridge_paths}
        for path in bridge_paths:
            if _lexists(path) and path.is_symlink():
                raise WorkspaceMigrationError(
                    f"Legacy lock must not be a symlink: {path.relative_to(root)}."
                )

        with ExitStack() as locks:
            if legacy_state_dir.is_dir():
                locks.enter_context(
                    FileLock(bridge_paths[0], timeout=30, preserve_lock_file=True)
                )
                locks.enter_context(
                    FileLock(bridge_paths[1], timeout=30, preserve_lock_file=True)
                )
            locks.enter_context(
                FileLock(
                    workspace_file_path(root, STATE_LOCK_FILE),
                    timeout=30,
                    preserve_lock_file=True,
                )
            )
            locks.enter_context(
                FileLock(
                    workspace_file_path(root, MAPPING_LOCK_FILE),
                    timeout=30,
                    preserve_lock_file=True,
                )
            )
            migrated = _migrate_legacy_workspace_locked(root)

        discarded_locks = []
        for path in bridge_paths:
            if _lexists(path):
                if not path.is_file():
                    raise WorkspaceMigrationError(
                        f"Legacy lock must be a regular file: {path.relative_to(root)}."
                    )
                os.remove(path)
            if bridge_existed[path]:
                discarded_locks.append(path.relative_to(root).as_posix())

        remaining_legacy = []
        if legacy_state_dir.is_dir():
            try:
                legacy_state_dir.rmdir()
            except OSError:
                remaining_legacy = sorted(
                    path.relative_to(root).as_posix()
                    for path in legacy_state_dir.iterdir()
                )

        ensure_workspace(root)
        changed = bool(migrated or discarded_locks)
        result = {
            "changed": changed,
            "migrated": migrated,
            "discarded_legacy_locks": discarded_locks,
            "remaining_legacy_paths": remaining_legacy,
        }
        if changed:
            with FileLock(
                workspace_file_path(root, STATE_LOCK_FILE),
                timeout=30,
                preserve_lock_file=True,
            ):
                _append_workspace_migration_audit(root, result)
        return result


def _migrate_legacy_workspace_locked(root: Path) -> list[dict[str, Any]]:
    """Perform a prevalidated migration while old and new state locks are held."""

    pending: list[tuple[str, Path, str, Path, bytes | None]] = []
    for source_relative, target_relative in LEGACY_PATHS.items():
        source = root / source_relative
        if not _lexists(source):
            continue
        target = root / target_relative
        if source.is_symlink() or target.is_symlink():
            raise WorkspaceMigrationError(
                f"Refusing workspace migration through a symlink: {source_relative}."
            )
        if _lexists(target):
            raise WorkspaceMigrationConflict(
                "Both legacy and canonical workspace paths exist; refusing to "
                f"choose between {source_relative} and {target_relative}."
            )
        expects_directory = source_relative in LEGACY_DIRECTORY_PATHS
        if expects_directory and not source.is_dir():
            raise WorkspaceMigrationError(
                f"Legacy path must be a directory: {source_relative}."
            )
        if not expects_directory and not source.is_file():
            raise WorkspaceMigrationError(
                f"Legacy path must be a regular file: {source_relative}."
            )
        normalized_payload = (
            _normalized_legacy_config(source)
            if source_relative == ".aio-agentic-sdlc.json"
            else None
        )
        if source_relative == "backlog.json":
            _validate_legacy_backlog(source)
        elif source_relative in {"intention-dag.yaml", "reality-dag.yaml"}:
            _validate_legacy_dag(source)
        elif source_relative == ".aio-sdlc/state-audit.jsonl":
            normalized_payload = _normalized_legacy_audit(source)
        pending.append(
            (source_relative, source, target_relative, target, normalized_payload)
        )

    migrated: list[dict[str, Any]] = []
    for source_relative, source, target_relative, target, payload in pending:
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            os.replace(source, target)
            migrated.append(
                {
                    "source": source_relative,
                    "target": target_relative,
                    "kind": "directory",
                }
            )
            continue

        source_hash = _sha256(source)
        if payload is not None:
            _atomic_write(target, payload)
            os.remove(source)
            target_hash = hashlib.sha256(payload).hexdigest()
        else:
            os.replace(source, target)
            target_hash = source_hash
        migrated.append(
            {
                "source": source_relative,
                "target": target_relative,
                "kind": "file",
                "source_sha256": source_hash,
                "target_sha256": target_hash,
            }
        )
    return migrated


def _append_workspace_migration_audit(root: Path, result: dict[str, Any]) -> None:
    audit_path = workspace_file_path(root, AUDIT_FILE)
    event = {
        "operation": "workspace.migrate",
        "phase": "committed",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        **result,
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = False
    if audit_path.exists() and audit_path.stat().st_size:
        with audit_path.open("rb") as reader:
            reader.seek(-1, os.SEEK_END)
            needs_newline = reader.read(1) != b"\n"
    with audit_path.open("ab") as handle:
        if needs_newline:
            handle.write(b"\n")
        handle.write((json.dumps(event, sort_keys=True) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
