import builtins
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from aio_agentic_sdlc.cli import migrate_ids_cmd
from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Metadata, Node, NodeType
from aio_agentic_sdlc.intent_migration import LegacyIntentMigrator
from aio_agentic_sdlc.workspace import INTENTION_DAG_FILE, REALITY_DAG_FILE


class DummyArgs:
    pass


def test_migrate_ids_maintains_cross_file_consistency(tmpdir, monkeypatch):
    monkeypatch.chdir(tmpdir)

    intention_data = {
        "metadata": {"name": "Intent", "version": "1.0"},
        "nodes": [{"id": "shared-node-1", "type": "module", "name": "Shared"}],
        "edges": [],
    }
    reality_data = {
        "metadata": {"name": "Reality", "version": "1.0"},
        "nodes": [{"id": "shared-node-1", "type": "module", "name": "Shared"}],
        "edges": [],
    }

    (tmpdir / ".aio-agentic-sdlc").ensure(dir=True)
    with open(INTENTION_DAG_FILE, "w") as f:
        yaml.dump(intention_data, f)
    with open(REALITY_DAG_FILE, "w") as f:
        yaml.dump(reality_data, f)

    migrate_ids_cmd(DummyArgs())

    with open(INTENTION_DAG_FILE, "r") as f:
        int_data = yaml.safe_load(f)
    with open(REALITY_DAG_FILE, "r") as f:
        real_data = yaml.safe_load(f)

    int_id = int_data["nodes"][0]["id"]
    real_id = real_data["nodes"][0]["id"]

    assert int_id == real_id, f"IDs diverged! Intention: {int_id}, Reality: {real_id}"


def test_migrate_ids_rejects_duplicate_raw_ids_without_mutating_either_dag(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    workspace = tmp_path / ".aio-agentic-sdlc"
    workspace.mkdir()
    intention_path = tmp_path / INTENTION_DAG_FILE
    reality_path = tmp_path / REALITY_DAG_FILE
    duplicate = {
        "nodes": [
            {"id": "duplicated-legacy-id", "type": "module", "name": "First"},
            {"id": "duplicated-legacy-id", "type": "module", "name": "Second"},
        ],
        "edges": [],
    }
    reality = {
        "nodes": [{"id": "reality-legacy-id", "type": "module", "name": "Reality"}],
        "edges": [],
    }
    intention_path.write_text(yaml.safe_dump(duplicate), encoding="utf-8")
    reality_path.write_text(yaml.safe_dump(reality), encoding="utf-8")
    intention_before = intention_path.read_bytes()
    reality_before = reality_path.read_bytes()

    with pytest.raises(ValueError, match="duplicate node IDs before migration"):
        migrate_ids_cmd(DummyArgs())

    assert intention_path.read_bytes() == intention_before
    assert reality_path.read_bytes() == reality_before


def test_migrate_ids_rolls_back_intention_when_reality_replace_fails(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    workspace = tmp_path / ".aio-agentic-sdlc"
    workspace.mkdir()
    intention_path = tmp_path / INTENTION_DAG_FILE
    reality_path = tmp_path / REALITY_DAG_FILE
    intention = {
        "metadata": {"name": "Intent", "version": "1.0"},
        "nodes": [{"id": "shared-legacy-id", "type": "module", "name": "Intent"}],
        "edges": [],
    }
    reality = {
        "metadata": {"name": "Reality", "version": "1.0"},
        "nodes": [{"id": "shared-legacy-id", "type": "module", "name": "Reality"}],
        "edges": [],
    }
    intention_path.write_text(yaml.safe_dump(intention), encoding="utf-8")
    reality_path.write_text(yaml.safe_dump(reality), encoding="utf-8")
    intention_before = intention_path.read_bytes()
    reality_before = reality_path.read_bytes()
    original_replace = __import__("os").replace
    replacements = 0

    def fail_second_commit(source, target):
        nonlocal replacements
        if str(source).endswith(".tmp") and ".rollback." not in str(source):
            replacements += 1
            if replacements == 2:
                raise OSError("simulated Reality replacement failure")
        return original_replace(source, target)

    monkeypatch.setattr("aio_agentic_sdlc.cli.os.replace", fail_second_commit)

    with pytest.raises(OSError, match="simulated Reality replacement failure"):
        migrate_ids_cmd(DummyArgs())

    assert intention_path.read_bytes() == intention_before
    assert reality_path.read_bytes() == reality_before


def test_migrate_ids_serializes_with_intent_migration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    intention_path = Path(INTENTION_DAG_FILE).resolve()
    reality_path = Path(REALITY_DAG_FILE).resolve()
    intention_path.parent.mkdir(parents=True)
    node = Node(
        id="00000000-0000-0000-0000-0000000000a1",
        type=NodeType.COMPONENT,
        name="Legacy Worker",
        description="Preserved intent.",
    )
    manager = DAGManager(Metadata(name="Intent", version="1.0"), [node], [])
    manager.save(str(intention_path))
    manager.save(str(reality_path))
    migrator = LegacyIntentMigrator(tmp_path)
    plan = migrator.plan(
        recorded_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        actor="sdlc_cartographer",
        generator_version="aio-agentic-sdlc/test",
    )
    original_open = builtins.open
    original_load = DAGManager.load
    migrate_ids_has_lock = threading.Event()
    release_migrate_ids = threading.Event()
    migration_loaded = threading.Event()
    outcomes = {}

    def blocked_open(file, mode="r", *args, **kwargs):
        if (
            threading.current_thread().name == "id-writer"
            and "r" in mode
            and Path(file).resolve() == intention_path
        ):
            migrate_ids_has_lock.set()
            assert release_migrate_ids.wait(timeout=5)
        return original_open(file, mode, *args, **kwargs)

    def observed_load(filepath):
        if threading.current_thread().name == "migration-writer":
            migration_loaded.set()
        return original_load(filepath)

    monkeypatch.setattr(builtins, "open", blocked_open)
    monkeypatch.setattr(DAGManager, "load", staticmethod(observed_load))

    def run_id_migration():
        try:
            migrate_ids_cmd(DummyArgs())
            outcomes["ids"] = "complete"
        except Exception as error:  # pragma: no cover - assertion reports the error
            outcomes["ids"] = error

    def run_intent_migration():
        try:
            outcomes["intent"] = migrator.apply(plan)
        except Exception as error:  # pragma: no cover - assertion reports the error
            outcomes["intent"] = error

    id_thread = threading.Thread(target=run_id_migration, name="id-writer")
    intent_thread = threading.Thread(
        target=run_intent_migration,
        name="migration-writer",
    )
    id_thread.start()
    assert migrate_ids_has_lock.wait(timeout=5)
    intent_thread.start()

    assert not migration_loaded.wait(timeout=0.2)
    release_migrate_ids.set()
    id_thread.join(timeout=5)
    intent_thread.join(timeout=5)

    assert not id_thread.is_alive()
    assert not intent_thread.is_alive()
    assert outcomes["ids"] == "complete", outcomes["ids"]
    assert isinstance(outcomes["intent"], dict), outcomes["intent"]
    DAGManager.load(str(intention_path)).validate_intent_ir(require_all=True)
