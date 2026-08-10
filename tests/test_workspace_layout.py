import json
import threading
from pathlib import Path

import pytest

from aio_agentic_sdlc import core
from aio_agentic_sdlc.config import save_config
from aio_agentic_sdlc.workspace import (
    ARCHIVE_DIR,
    BACKLOG_FILE,
    CHANGES_DIR,
    CONFIG_FILE,
    INBOX_DIR,
    INTENTION_DAG_FILE,
    REALITY_DAG_FILE,
    RESEARCH_SPIKES_DIR,
    SPECS_DIR,
    WORKSPACE_DIR,
    WorkspaceMigrationConflict,
    WorkspaceMigrationError,
    WorkspaceMigrationRequired,
    ensure_workspace,
    migrate_legacy_workspace,
    workspace_migration_lock,
    workspace_path,
)


def test_framework_paths_share_the_full_project_name_parent():
    assert WORKSPACE_DIR == ".aio-agentic-sdlc"
    assert INTENTION_DAG_FILE == ".aio-agentic-sdlc/intention-dag.yaml"
    assert REALITY_DAG_FILE == ".aio-agentic-sdlc/reality-dag.yaml"
    assert BACKLOG_FILE == ".aio-agentic-sdlc/backlog.json"
    assert CONFIG_FILE == ".aio-agentic-sdlc/config.json"
    assert INBOX_DIR == ".aio-agentic-sdlc/inbox"
    assert SPECS_DIR == ".aio-agentic-sdlc/specs"
    assert CHANGES_DIR == ".aio-agentic-sdlc/changes"
    assert ARCHIVE_DIR == ".aio-agentic-sdlc/archive"
    assert RESEARCH_SPIKES_DIR == ".aio-agentic-sdlc/research-spikes"


def test_workspace_path_is_project_relative(tmp_path):
    assert workspace_path(tmp_path, "specs", "feature.md") == (
        tmp_path / ".aio-agentic-sdlc" / "specs" / "feature.md"
    )


def test_ensure_workspace_eagerly_creates_operational_directories(tmp_path):
    root = ensure_workspace(tmp_path)

    assert root == tmp_path / ".aio-agentic-sdlc"
    for relative in ("inbox", "specs", "changes", "archive", "research-spikes"):
        assert (root / relative).is_dir()
    assert not (root / "intention-dag.yaml").exists()
    assert not (root / "reality-dag.yaml").exists()


def test_no_short_name_state_directory_is_created(tmp_path):
    ensure_workspace(tmp_path)

    assert not (Path(tmp_path) / ".aio-sdlc").exists()


def test_legacy_workspace_migration_preserves_state_and_audits_provenance(tmp_path):
    legacy_backlog = tmp_path / "backlog.json"
    legacy_backlog.write_bytes(b'{"nodes":{"Keep":{}},"edges":[]}')
    legacy_config = tmp_path / ".aio-agentic-sdlc.json"
    legacy_config.write_text(
        json.dumps(
            {
                "core": {"mode": "github", "validation_mode": "strict"},
                "github": {"repo": "retired/remote"},
                "hierarchy": {"1": ["Feature"], "2": ["Task"]},
            }
        ),
        encoding="utf-8",
    )
    legacy_state = tmp_path / ".aio-sdlc"
    legacy_state.mkdir()
    legacy_audit = legacy_state / "state-audit.jsonl"
    legacy_audit.write_text('{"operation":"existing"}', encoding="utf-8")
    (legacy_state / "state.lock").touch()
    (legacy_state / "mapping.lock").touch()

    result = migrate_legacy_workspace(tmp_path)

    assert result["changed"] is True
    assert not legacy_backlog.exists()
    assert not legacy_config.exists()
    assert not legacy_audit.exists()
    assert not legacy_state.exists()
    assert result["discarded_legacy_locks"] == [
        ".aio-sdlc/state.lock",
        ".aio-sdlc/mapping.lock",
    ]
    assert result["remaining_legacy_paths"] == []
    assert (tmp_path / BACKLOG_FILE).read_bytes() == b'{"nodes":{"Keep":{}},"edges":[]}'
    config = json.loads((tmp_path / CONFIG_FILE).read_text(encoding="utf-8"))
    assert config == {
        "core": {"mode": "local", "validation_mode": "strict"},
        "hierarchy": {"1": ["Feature"], "2": ["Task"]},
    }
    events = [
        json.loads(line)
        for line in (tmp_path / ".aio-agentic-sdlc/state-audit.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert events[0] == {"operation": "existing"}
    assert events[-1]["operation"] == "workspace.migrate"
    migrated_sources = {item["source"] for item in events[-1]["migrated"]}
    assert migrated_sources == {
        ".aio-agentic-sdlc.json",
        ".aio-sdlc/state-audit.jsonl",
        "backlog.json",
    }


def test_normal_commands_fail_before_legacy_state_can_be_hidden(tmp_path):
    (tmp_path / "backlog.json").write_text(
        json.dumps({"nodes": {"Visible": {}}, "edges": []}), encoding="utf-8"
    )

    with pytest.raises(WorkspaceMigrationRequired, match="migrate-state"):
        core.load_backlog(str(tmp_path))

    assert not (tmp_path / BACKLOG_FILE).exists()


def test_workspace_migration_refuses_dual_layout_conflicts_without_changes(tmp_path):
    legacy = tmp_path / "backlog.json"
    canonical = tmp_path / BACKLOG_FILE
    canonical.parent.mkdir(parents=True)
    legacy.write_bytes(b'{"nodes":{"Legacy":{}},"edges":[]}')
    canonical.write_bytes(b'{"nodes":{"Canonical":{}},"edges":[]}')

    with pytest.raises(WorkspaceMigrationConflict, match="Both legacy and canonical"):
        migrate_legacy_workspace(tmp_path)

    assert legacy.read_bytes() == b'{"nodes":{"Legacy":{}},"edges":[]}'
    assert canonical.read_bytes() == b'{"nodes":{"Canonical":{}},"edges":[]}'
    assert not (tmp_path / ".aio-agentic-sdlc/state-audit.jsonl").exists()


def test_host_repository_spec_directory_is_never_claimed_as_framework_state(tmp_path):
    host_spec = tmp_path / "specs/product.md"
    host_spec.parent.mkdir()
    host_spec.write_text("# Host-owned specification\n", encoding="utf-8")

    result = migrate_legacy_workspace(tmp_path)
    core.save_backlog({"nodes": {}, "edges": []}, str(tmp_path))

    assert result == {
        "changed": False,
        "migrated": [],
        "discarded_legacy_locks": [],
        "remaining_legacy_paths": [],
    }
    assert host_spec.read_text(encoding="utf-8") == "# Host-owned specification\n"
    assert not (tmp_path / ".aio-agentic-sdlc/specs/product.md").exists()


def test_non_aio_root_backlog_is_rejected_without_mutation(tmp_path):
    host_backlog = tmp_path / "backlog.json"
    payload = b'{"tickets":["host-owned"]}'
    host_backlog.write_bytes(payload)

    with pytest.raises(WorkspaceMigrationError, match="does not match an AIO"):
        migrate_legacy_workspace(tmp_path)

    assert host_backlog.read_bytes() == payload
    assert not (tmp_path / BACKLOG_FILE).exists()


def test_migration_repairs_a_truncated_legacy_audit_tail(tmp_path):
    legacy_state = tmp_path / ".aio-sdlc"
    legacy_state.mkdir()
    (legacy_state / "state-audit.jsonl").write_bytes(
        b'{"operation":"complete"}\n{"transaction_id":"interrupted'
    )

    migrate_legacy_workspace(tmp_path)

    events = [
        json.loads(line)
        for line in (tmp_path / ".aio-agentic-sdlc/state-audit.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [event["operation"] for event in events] == [
        "complete",
        "audit.recover",
        "workspace.migrate",
    ]
    assert events[1]["phase"] == "audit_tail_truncated"
    assert events[1]["discarded_bytes"] > 0


def test_normal_state_operations_wait_for_the_workspace_migration_lock(tmp_path):
    (tmp_path / "backlog.json").write_text(
        json.dumps({"nodes": {"Legacy": {}}, "edges": []}), encoding="utf-8"
    )
    started = threading.Event()
    finished = threading.Event()
    failures = []

    def load_in_thread():
        started.set()
        try:
            core.load_backlog(str(tmp_path))
        except Exception as exc:  # noqa: BLE001 - captured for cross-thread assertion
            failures.append(exc)
        finally:
            finished.set()

    with workspace_migration_lock(tmp_path):
        worker = threading.Thread(target=load_in_thread)
        worker.start()
        assert started.wait(timeout=1)
        assert not finished.wait(timeout=0.1)

    worker.join(timeout=2)
    assert not worker.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], WorkspaceMigrationRequired)


def test_state_and_config_reject_a_symlinked_canonical_parent(tmp_path):
    redirect_target = tmp_path / "redirect-target"
    redirect_target.mkdir()
    workspace_link = tmp_path / WORKSPACE_DIR
    try:
        workspace_link.symlink_to(redirect_target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")

    with pytest.raises(WorkspaceMigrationError, match="real directory"):
        core.save_backlog({"nodes": {}, "edges": []}, str(tmp_path))
    with pytest.raises(WorkspaceMigrationError, match="real directory"):
        save_config({"core": {"mode": "local"}}, str(tmp_path))

    assert list(redirect_target.iterdir()) == []


@pytest.mark.parametrize("relative_path", ["config.json", "state-audit.jsonl"])
def test_writable_workspace_files_reject_leaf_symlinks(tmp_path, relative_path):
    workspace = ensure_workspace(tmp_path)
    redirect_target = tmp_path / f"redirect-{relative_path}"
    redirect_target.write_text("sentinel", encoding="utf-8")
    link = workspace / relative_path
    try:
        link.symlink_to(redirect_target)
    except OSError as exc:
        pytest.skip(f"File symlinks are unavailable: {exc}")

    with pytest.raises(WorkspaceMigrationError, match="regular file"):
        if relative_path == "config.json":
            save_config({"core": {"mode": "local"}}, str(tmp_path))
        else:
            core.save_backlog({"nodes": {}, "edges": []}, str(tmp_path))

    assert redirect_target.read_text(encoding="utf-8") == "sentinel"
