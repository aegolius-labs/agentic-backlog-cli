import json
import sys

import pytest

from aio_agentic_sdlc import core
from aio_agentic_sdlc.cli import main
from aio_agentic_sdlc.state import (
    AUDIT_FILE,
    BACKLOG_FILE,
    CURRENT_BACKLOG_SCHEMA_VERSION,
    BacklogConflictError,
    UnsupportedBacklogSchema,
    migrate_backlog,
    retire_legacy_backlog,
)
from aio_agentic_sdlc.workspace import (
    LEGACY_DIR,
    WORKSPACE_DIR,
    WorkspaceMigrationError,
    ensure_workspace,
)


def _audit_events(project_path):
    audit_path = project_path / AUDIT_FILE
    return [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_missing_backlog_uses_current_schema(tmp_path):
    assert core.load_backlog(str(tmp_path)) == {
        "schema_version": CURRENT_BACKLOG_SCHEMA_VERSION,
        "revision": 0,
        "nodes": {},
        "edges": [],
    }


def test_legacy_items_migrate_deterministically_without_an_implicit_write(tmp_path):
    backlog_path = tmp_path / BACKLOG_FILE
    backlog_path.parent.mkdir(parents=True)
    backlog_path.write_text(
        json.dumps(
            {
                "items": {
                    "Child": {
                        "description": "Legacy item",
                        "requires": ["Dependency"],
                        "parent_id": "Parent",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    first = core.load_backlog(str(tmp_path))
    second = core.load_backlog(str(tmp_path))

    assert first == second
    assert first["schema_version"] == CURRENT_BACKLOG_SCHEMA_VERSION
    assert first["nodes"]["Child"]["item_type"] == "Task"
    assert first["edges"] == [
        {"from": "Child", "to": "Dependency", "relation": "requires"},
        {"from": "Child", "to": "Parent", "relation": "parent"},
    ]
    assert "schema_version" not in json.loads(backlog_path.read_text(encoding="utf-8"))


def test_explicit_migration_persists_current_schema_and_audits_it(tmp_path):
    backlog_path = tmp_path / BACKLOG_FILE
    backlog_path.parent.mkdir(parents=True)
    backlog_path.write_text(
        json.dumps({"nodes": {"Task": {"description": "Keep me"}}, "edges": []}),
        encoding="utf-8",
    )

    result = migrate_backlog(str(tmp_path))

    assert result == {"from_version": 0, "to_version": 1, "changed": True}
    persisted = json.loads(backlog_path.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == CURRENT_BACKLOG_SCHEMA_VERSION
    assert persisted["revision"] == 1
    assert persisted["nodes"]["Task"]["description"] == "Keep me"
    events = _audit_events(tmp_path)
    assert [event["phase"] for event in events] == ["prepared", "committed"]
    assert {event["operation"] for event in events} == {"backlog.migrate"}


def test_cli_exposes_explicit_local_state_migration(tmp_path, monkeypatch, capsys):
    backlog_path = tmp_path / BACKLOG_FILE
    backlog_path.parent.mkdir(parents=True)
    backlog_path.write_text(json.dumps({"nodes": {}, "edges": []}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["aio-sdlc", "migrate-state"])

    main()

    assert json.loads(capsys.readouterr().out) == {
        "from_version": 0,
        "to_version": CURRENT_BACKLOG_SCHEMA_VERSION,
        "changed": True,
        "workspace": {
            "changed": False,
            "migrated": [],
            "discarded_legacy_locks": [],
            "remaining_legacy_paths": [],
        },
    }


def test_cli_migrates_legacy_layout_before_schema_migration(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "backlog.json").write_text(
        json.dumps({"nodes": {"Preserved": {}}, "edges": []}), encoding="utf-8"
    )
    (tmp_path / ".aio-agentic-sdlc.json").write_text(
        json.dumps(
            {
                "core": {"mode": "github", "validation_mode": "strict"},
                "github": {"repo": "retired/remote"},
                "hierarchy": {"1": ["Task"]},
            }
        ),
        encoding="utf-8",
    )
    legacy_state = tmp_path / ".aio-sdlc"
    legacy_state.mkdir()
    (legacy_state / "state-audit.jsonl").write_text(
        '{"operation":"legacy.event"}\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["aio-sdlc", "migrate-state"])

    main()

    result = json.loads(capsys.readouterr().out)
    assert result["workspace"]["changed"] is True
    assert {item["source"] for item in result["workspace"]["migrated"]} == {
        ".aio-agentic-sdlc.json",
        ".aio-sdlc/state-audit.jsonl",
        "backlog.json",
    }
    assert result["changed"] is True
    assert (
        "Preserved"
        in json.loads((tmp_path / BACKLOG_FILE).read_text(encoding="utf-8"))["nodes"]
    )
    config = json.loads(
        (tmp_path / ".aio-agentic-sdlc/config.json").read_text(encoding="utf-8")
    )
    assert config["core"] == {"mode": "local", "validation_mode": "strict"}
    assert "github" not in config


def test_legacy_generated_backlog_is_archived_and_retired_idempotently(tmp_path):
    legacy_path = tmp_path / ".agentic-backlog.json"
    legacy_payload = b'{"nodes":{"Legacy":{"description":"generated diff"}}}'
    legacy_path.write_bytes(legacy_payload)

    first = retire_legacy_backlog(str(tmp_path))
    second = retire_legacy_backlog(str(tmp_path))

    assert first["changed"] is True
    assert second == {"changed": False, "archive": None, "sha256": None}
    assert not legacy_path.exists()
    archive_path = tmp_path / first["archive"]
    assert archive_path.read_bytes() == legacy_payload
    event = _audit_events(tmp_path)[-1]
    assert event["operation"] == "legacy-backlog.retire"
    assert event["phase"] == "committed"
    assert event["sha256"] == first["sha256"]


def test_legacy_backlog_retirement_rejects_a_symlinked_archive_parent(tmp_path):
    legacy_path = tmp_path / ".agentic-backlog.json"
    payload = b'{"nodes":{"Legacy":{}}}'
    legacy_path.write_bytes(payload)
    workspace = ensure_workspace(tmp_path)
    redirect_target = tmp_path / "archive-redirect"
    redirect_target.mkdir()
    archive_parent = tmp_path / LEGACY_DIR
    try:
        archive_parent.symlink_to(redirect_target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")

    with pytest.raises(WorkspaceMigrationError, match="real directory"):
        retire_legacy_backlog(str(tmp_path))

    assert legacy_path.read_bytes() == payload
    assert list(redirect_target.iterdir()) == []
    assert workspace.is_dir()


def test_future_schema_is_rejected_without_modifying_state(tmp_path):
    backlog_path = tmp_path / BACKLOG_FILE
    backlog_path.parent.mkdir(parents=True)
    original = {
        "schema_version": CURRENT_BACKLOG_SCHEMA_VERSION + 1,
        "nodes": {},
        "edges": [],
    }
    backlog_path.write_text(json.dumps(original), encoding="utf-8")

    with pytest.raises(UnsupportedBacklogSchema, match="newer than supported"):
        core.load_backlog(str(tmp_path))

    assert json.loads(backlog_path.read_text(encoding="utf-8")) == original
    assert not (tmp_path / AUDIT_FILE).exists()


def test_save_writes_a_prepared_and_committed_audit_pair(tmp_path):
    core.save_backlog({"nodes": {}, "edges": []}, str(tmp_path), operation="test.save")

    events = _audit_events(tmp_path)
    assert [event["phase"] for event in events] == ["prepared", "committed"]
    assert events[0]["transaction_id"] == events[1]["transaction_id"]
    assert events[0]["before_sha256"] is None
    assert events[0]["after_sha256"] == events[1]["after_sha256"]
    assert events[0]["schema_version"] == CURRENT_BACKLOG_SCHEMA_VERSION
    assert {event["operation"] for event in events} == {"test.save"}


def test_stale_writer_is_rejected_instead_of_losing_a_concurrent_update(tmp_path):
    core.save_backlog({"nodes": {}, "edges": []}, str(tmp_path), operation="seed")
    first_writer = core.load_backlog(str(tmp_path))
    stale_writer = core.load_backlog(str(tmp_path))

    first_writer["nodes"]["First"] = {"description": "Committed first"}
    core.save_backlog(first_writer, str(tmp_path), operation="writer.first")
    stale_writer["nodes"]["Stale"] = {"description": "Must not overwrite First"}

    with pytest.raises(BacklogConflictError, match="stale revision"):
        core.save_backlog(stale_writer, str(tmp_path), operation="writer.stale")

    persisted = core.load_backlog(str(tmp_path))
    assert "First" in persisted["nodes"]
    assert "Stale" not in persisted["nodes"]


def test_unversioned_writer_cannot_replace_versioned_state(tmp_path):
    core.save_backlog({"nodes": {}, "edges": []}, str(tmp_path), operation="seed")

    with pytest.raises(BacklogConflictError, match="stale revision 0"):
        core.save_backlog(
            {"nodes": {"Unsafe": {}}, "edges": []},
            str(tmp_path),
            operation="legacy.writer",
        )


def test_failed_replace_preserves_state_and_is_reconciled_as_rolled_back(
    tmp_path, monkeypatch
):
    from aio_agentic_sdlc import state

    original = {"nodes": {"Existing": {"description": "Keep"}}, "edges": []}
    core.save_backlog(original, str(tmp_path), operation="seed")
    original_replace = state.os.replace

    def fail_replace(*_args, **_kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(state.os, "replace", fail_replace)
    replacement = core.load_backlog(str(tmp_path))
    replacement["nodes"] = {}
    with pytest.raises(OSError, match="simulated replace failure"):
        core.save_backlog(replacement, str(tmp_path), operation="test.fail")
    monkeypatch.setattr(state.os, "replace", original_replace)

    loaded = core.load_backlog(str(tmp_path))

    assert loaded["nodes"] == original["nodes"]
    assert _audit_events(tmp_path)[-1]["phase"] == "rolled_back"
    assert list((tmp_path / WORKSPACE_DIR).glob(".backlog.json.*.tmp")) == []


def test_load_recovers_commit_when_audit_commit_was_interrupted(tmp_path, monkeypatch):
    from aio_agentic_sdlc import state

    core.save_backlog({"nodes": {}, "edges": []}, str(tmp_path), operation="seed")
    original_append = state._append_audit_event

    def interrupt_commit(project_path, event):
        if event["phase"] == "committed":
            raise OSError("simulated audit interruption")
        return original_append(project_path, event)

    monkeypatch.setattr(state, "_append_audit_event", interrupt_commit)
    replacement = core.load_backlog(str(tmp_path))
    replacement["nodes"]["New"] = {"description": "Persisted"}
    with pytest.raises(OSError, match="simulated audit interruption"):
        core.save_backlog(
            replacement,
            str(tmp_path),
            operation="test.interrupted-commit",
        )
    monkeypatch.setattr(state, "_append_audit_event", original_append)

    loaded = core.load_backlog(str(tmp_path))

    assert "New" in loaded["nodes"]
    assert _audit_events(tmp_path)[-1]["phase"] == "recovered_commit"


def test_load_repairs_a_truncated_final_audit_record(tmp_path):
    core.save_backlog({"nodes": {}, "edges": []}, str(tmp_path), operation="seed")
    audit_path = tmp_path / AUDIT_FILE
    with audit_path.open("ab") as handle:
        handle.write(b'{"transaction_id":"interrupted')

    loaded = core.load_backlog(str(tmp_path))

    assert loaded["nodes"] == {}
    assert _audit_events(tmp_path)[-1]["phase"] == "audit_tail_truncated"
    assert audit_path.read_bytes().endswith(b"\n")
