import hashlib
import json
import os
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from aio_agentic_sdlc.dag_cli import cli
from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Edge, EdgeType, Metadata, Node, NodeType
from aio_agentic_sdlc.intent_migration import LegacyIntentMigrator
from aio_agentic_sdlc.workspace import INTENTION_DAG_FILE
from tests.test_intent_ir import _intent_ir

LEGACY_ID = "00000000-0000-0000-0000-0000000000a1"
EXISTING_ID = "00000000-0000-0000-0000-0000000000a2"
RECORDED_AT = datetime(2026, 8, 13, tzinfo=timezone.utc)


def _write_project(tmp_path):
    dag_path = tmp_path / INTENTION_DAG_FILE
    dag_path.parent.mkdir(parents=True)
    legacy = Node(
        id=LEGACY_ID,
        type=NodeType.COMPONENT,
        name="Legacy Worker",
        domain="core",
        description="Processes the preserved legacy work queue.",
    )
    existing = Node(
        id=EXISTING_ID,
        type=NodeType.COMPONENT,
        name="Existing Worker",
        intent=_intent_ir(),
    )
    edge = Edge(
        source=EXISTING_ID,
        target=LEGACY_ID,
        type=EdgeType.CALLS,
        description="Delegates preserved work to the legacy worker.",
    )
    DAGManager(Metadata(name="Intent", version="1.0"), [legacy, existing], [edge]).save(
        str(dag_path)
    )
    spec = tmp_path / ".aio-agentic-sdlc" / "specs" / "legacy-worker.md"
    spec.parent.mkdir()
    spec.write_text(
        "# Legacy Worker\n\nThe Legacy Worker processes the preserved legacy work queue.\n",
        encoding="utf-8",
    )
    unrelated = tmp_path / ".aio-agentic-sdlc" / "specs" / "other.md"
    unrelated.write_text(
        "# Other Component\n\nThe Legacy Worker is explicitly out of scope.\n\n"
        "title: Legacy Worker\n",
        encoding="utf-8",
    )
    return dag_path


def _plan(migrator):
    return migrator.plan(
        recorded_at=RECORDED_AT,
        actor="sdlc_cartographer",
        generator_version="aio-agentic-sdlc/test",
    )


def test_inventory_is_bounded_and_reports_complete_coverage(tmp_path):
    _write_project(tmp_path)
    migrator = LegacyIntentMigrator(tmp_path)

    report = migrator.inventory(max_items=0)

    assert report["summary"] == {
        "total_nodes": 2,
        "intent_ir_nodes": 1,
        "legacy_nodes": 1,
    }
    assert report["limit"] == {
        "max_items": 0,
        "total_items": 1,
        "returned_items": 0,
        "truncated": True,
    }
    assert report["items"] == []


def test_content_identity_and_plan_are_equal_for_lf_and_crlf_dags(tmp_path):
    lf_root = tmp_path / "lf"
    crlf_root = tmp_path / "crlf"
    lf_path = _write_project(lf_root)
    crlf_path = _write_project(crlf_root)
    crlf_path.write_bytes(crlf_path.read_bytes().replace(b"\n", b"\r\n"))

    lf_migrator = LegacyIntentMigrator(lf_root)
    crlf_migrator = LegacyIntentMigrator(crlf_root)
    lf_plan = _plan(lf_migrator)
    crlf_plan = _plan(crlf_migrator)

    assert lf_path.read_bytes() != crlf_path.read_bytes()
    assert lf_migrator.inventory()["source"] == crlf_migrator.inventory()["source"]
    assert lf_plan == crlf_plan
    assert lf_migrator.apply(lf_plan) == crlf_migrator.apply(crlf_plan)


@pytest.mark.parametrize("operation", ["inventory", "plan"])
def test_read_artifacts_serialize_with_structural_writers(
    tmp_path,
    monkeypatch,
    operation,
):
    dag_path = _write_project(tmp_path)
    migrator = LegacyIntentMigrator(tmp_path)
    original_legacy_nodes = LegacyIntentMigrator._legacy_nodes
    original_load = DAGManager.load
    reader_has_snapshot = threading.Event()
    release_reader = threading.Event()
    structural_loaded = threading.Event()
    outcomes = {}

    def blocked_legacy_nodes(manager):
        if threading.current_thread().name == "snapshot-reader":
            reader_has_snapshot.set()
            assert release_reader.wait(timeout=5)
        return original_legacy_nodes(manager)

    def observed_load(filepath):
        if threading.current_thread().name == "structural-writer":
            structural_loaded.set()
        return original_load(filepath)

    monkeypatch.setattr(
        LegacyIntentMigrator,
        "_legacy_nodes",
        staticmethod(blocked_legacy_nodes),
    )
    monkeypatch.setattr(DAGManager, "load", staticmethod(observed_load))

    def read_artifact():
        if operation == "inventory":
            outcomes["artifact"] = migrator.inventory()
        else:
            outcomes["artifact"] = _plan(migrator)

    def update_node():
        outcomes["structural"] = CliRunner().invoke(
            cli,
            [
                "node",
                "update",
                "--file",
                str(dag_path),
                "--id",
                LEGACY_ID,
                "--description",
                "Concurrent description.",
            ],
        )

    reader_thread = threading.Thread(target=read_artifact, name="snapshot-reader")
    writer_thread = threading.Thread(target=update_node, name="structural-writer")
    reader_thread.start()
    assert reader_has_snapshot.wait(timeout=5)
    writer_thread.start()

    assert not structural_loaded.wait(timeout=0.2)
    release_reader.set()
    reader_thread.join(timeout=5)
    writer_thread.join(timeout=5)

    assert not reader_thread.is_alive()
    assert not writer_thread.is_alive()
    assert outcomes["structural"].exit_code == 0, outcomes["structural"].output
    current = migrator.inventory()["source"]["sha256"]
    assert outcomes["artifact"]["source"]["sha256"] != current


def test_plan_is_deterministic_and_keeps_uncertain_intent_review_required(tmp_path):
    _write_project(tmp_path)
    migrator = LegacyIntentMigrator(tmp_path)

    first = _plan(migrator)
    second = _plan(migrator)

    assert first == second
    assert first["plan_sha256"] == second["plan_sha256"]
    item = first["items"][0]
    intent = item["intent"]
    assert item["node_id"] == LEGACY_ID
    assert intent["approval"]["state"] == "review_required"
    assert intent["ambiguities"][0]["status"] == "open"
    assert intent["acceptance_criteria"][0]["statement"] == (
        "Processes the preserved legacy work queue."
    )
    assert any(
        source["statement"] == "Delegates preserved work to the legacy worker."
        for source in intent["provenance"]
    )
    document_sources = [
        source for source in intent["provenance"] if source["source_type"] == "document"
    ]
    assert len(document_sources) == 1
    assert document_sources[0]["reference"].endswith("specs/legacy-worker.md:1")


def test_plan_bounds_duplicate_document_evidence_without_hiding_omissions(tmp_path):
    _write_project(tmp_path)
    specs = tmp_path / ".aio-agentic-sdlc" / "specs"
    for index in range(4):
        (specs / f"legacy-worker-{index}.md").write_text(
            "# Legacy Worker\n",
            encoding="utf-8",
        )

    item = _plan(LegacyIntentMigrator(tmp_path))["items"][0]["intent"]
    document_sources = [
        source for source in item["provenance"] if source["source_type"] == "document"
    ]

    assert len(document_sources) == 3
    assert any(
        "2 additional exact-title documents" in ambiguity["question"]
        for ambiguity in item["ambiguities"]
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
@pytest.mark.parametrize("nested", [False, True])
def test_plan_rejects_external_document_junctions(tmp_path, nested):
    _write_project(tmp_path)
    specs = tmp_path / ".aio-agentic-sdlc" / "specs"
    external = tmp_path.parent / f"{tmp_path.name}-external-documents-{nested}"
    external.mkdir()
    (external / "injected.md").write_text(
        "# Legacy Worker\n\nExternal mutable intent.\n",
        encoding="utf-8",
    )
    junction = specs / "external" if nested else specs
    if not nested:
        shutil.rmtree(specs)
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(external)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        shutil.rmtree(external)
        pytest.skip(f"junction creation unavailable: {completed.stderr}")
    try:
        assert not junction.is_symlink()
        with pytest.raises(ValueError, match="real directory"):
            _plan(LegacyIntentMigrator(tmp_path))
    finally:
        os.rmdir(junction)
        shutil.rmtree(external)


def test_apply_migrates_all_legacy_nodes_atomically_and_preserves_graph(tmp_path):
    dag_path = _write_project(tmp_path)
    before = DAGManager.load(str(dag_path))
    plan = _plan(LegacyIntentMigrator(tmp_path))

    result = LegacyIntentMigrator(tmp_path).apply(plan)

    after = DAGManager.load(str(dag_path))
    after.validate_intent_ir(require_all=True)
    assert result["migrated_nodes"] == 1
    assert result["strict_validation"] is True
    assert after.edges == before.edges
    assert after.get_node(EXISTING_ID) == before.get_node(EXISTING_ID)
    assert after.get_node(LEGACY_ID).model_dump(exclude={"intent"}) == before.get_node(
        LEGACY_ID
    ).model_dump(exclude={"intent"})
    assert after.get_node(LEGACY_ID).intent.approval.state.value == "review_required"


def test_apply_rejects_stale_source_without_mutation(tmp_path):
    dag_path = _write_project(tmp_path)
    migrator = LegacyIntentMigrator(tmp_path)
    plan = _plan(migrator)
    manager = DAGManager.load(str(dag_path))
    manager.update_node(LEGACY_ID, description="A concurrent revision.")
    manager.save(str(dag_path))
    before = dag_path.read_bytes()

    with pytest.raises(ValueError, match="stale migration plan"):
        migrator.apply(plan)

    assert dag_path.read_bytes() == before


def test_apply_rejects_invalid_plan_without_partial_mutation(tmp_path):
    dag_path = _write_project(tmp_path)
    plan = _plan(LegacyIntentMigrator(tmp_path))
    plan = json.loads(json.dumps(plan))
    plan["items"][0]["intent"]["acceptance_criteria"] = []
    before = dag_path.read_bytes()

    with pytest.raises(ValueError):
        LegacyIntentMigrator(tmp_path).apply(plan)

    assert dag_path.read_bytes() == before


def test_apply_rejects_validly_redigested_semantic_tampering(tmp_path):
    dag_path = _write_project(tmp_path)
    plan = json.loads(json.dumps(_plan(LegacyIntentMigrator(tmp_path))))
    plan["items"][0]["intent"]["acceptance_criteria"][0][
        "statement"
    ] = "Invented behavior that was not produced by the compiler."
    unsigned = {key: value for key, value in plan.items() if key != "plan_sha256"}
    canonical = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    plan["plan_sha256"] = hashlib.sha256(canonical).hexdigest()
    before = dag_path.read_bytes()

    with pytest.raises(ValueError, match="deterministic compiler output"):
        LegacyIntentMigrator(tmp_path).apply(plan)

    assert dag_path.read_bytes() == before


def test_apply_preserves_canonical_dag_when_atomic_replace_fails(tmp_path, monkeypatch):
    dag_path = _write_project(tmp_path)
    plan = _plan(LegacyIntentMigrator(tmp_path))
    before = dag_path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("aio_agentic_sdlc.dag_manager.os.replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        LegacyIntentMigrator(tmp_path).apply(plan)

    assert dag_path.read_bytes() == before


@pytest.mark.parametrize("operation", ["node", "edge"])
def test_migration_serializes_with_structural_cli_writers(
    tmp_path,
    monkeypatch,
    operation,
):
    dag_path = _write_project(tmp_path)
    migrator = LegacyIntentMigrator(tmp_path)
    plan = _plan(migrator)
    original_load = DAGManager.load
    original_save = DAGManager.save
    migration_at_save = threading.Event()
    release_migration = threading.Event()
    structural_loaded = threading.Event()
    outcomes = {}

    def observed_load(filepath):
        if threading.current_thread().name == "structural-writer":
            structural_loaded.set()
        return original_load(filepath)

    def blocked_save(manager, filepath):
        if threading.current_thread().name == "migration-writer":
            migration_at_save.set()
            assert release_migration.wait(timeout=5)
        return original_save(manager, filepath)

    monkeypatch.setattr(DAGManager, "load", staticmethod(observed_load))
    monkeypatch.setattr(DAGManager, "save", blocked_save)

    def run_migration():
        try:
            outcomes["migration"] = migrator.apply(plan)
        except Exception as error:  # pragma: no cover - assertion reports the error
            outcomes["migration"] = error

    def run_structural_command():
        arguments = [
            "node",
            "update",
            "--file",
            str(dag_path),
            "--id",
            LEGACY_ID,
            "--description",
            "Updated after serialized migration.",
        ]
        if operation == "edge":
            arguments = [
                "edge",
                "add",
                "--file",
                str(dag_path),
                "--source",
                LEGACY_ID,
                "--target",
                EXISTING_ID,
                "--type",
                "reads",
            ]
        outcomes["structural"] = CliRunner().invoke(cli, arguments)

    migration_thread = threading.Thread(
        target=run_migration,
        name="migration-writer",
    )
    structural_thread = threading.Thread(
        target=run_structural_command,
        name="structural-writer",
    )
    migration_thread.start()
    assert migration_at_save.wait(timeout=5)
    structural_thread.start()

    assert not structural_loaded.wait(timeout=0.2)
    release_migration.set()
    migration_thread.join(timeout=5)
    structural_thread.join(timeout=5)

    assert not migration_thread.is_alive()
    assert not structural_thread.is_alive()
    assert isinstance(outcomes["migration"], dict), outcomes["migration"]
    assert outcomes["structural"].exit_code == 0, outcomes["structural"].output
    after = DAGManager.load(str(dag_path))
    assert after.get_node(LEGACY_ID).intent is not None
    if operation == "node":
        assert (
            after.get_node(LEGACY_ID).description
            == "Updated after serialized migration."
        )
    else:
        assert any(
            edge.source == LEGACY_ID
            and edge.target == EXISTING_ID
            and edge.type == EdgeType.READS
            for edge in after.edges
        )


def test_cli_inventory_plan_and_apply_complete_strict_migration(tmp_path):
    dag_path = _write_project(tmp_path)
    changes = tmp_path / ".aio-agentic-sdlc" / "changes" / "migration"
    inventory_path = changes / "coverage.json"
    plan_path = changes / "plan.json"
    result_path = changes / "result.json"
    runner = CliRunner()

    inventory = runner.invoke(
        cli,
        [
            "intent",
            "inventory",
            "--project-path",
            str(tmp_path),
            "--max-items",
            "1",
            "--output",
            str(inventory_path),
        ],
    )
    plan = runner.invoke(
        cli,
        [
            "intent",
            "plan-migration",
            "--project-path",
            str(tmp_path),
            "--recorded-at",
            RECORDED_AT.isoformat(),
            "--actor",
            "sdlc_cartographer",
            "--generator-version",
            "aio-agentic-sdlc/test",
            "--output",
            str(plan_path),
        ],
    )
    apply = runner.invoke(
        cli,
        [
            "intent",
            "apply-migration",
            "--project-path",
            str(tmp_path),
            "--plan-file",
            str(plan_path),
            "--output",
            str(result_path),
        ],
    )

    assert inventory.exit_code == 0, inventory.output
    assert plan.exit_code == 0, plan.output
    assert apply.exit_code == 0, apply.output
    assert (
        json.loads(inventory_path.read_text(encoding="utf-8"))["summary"][
            "legacy_nodes"
        ]
        == 1
    )
    assert (
        json.loads(result_path.read_text(encoding="utf-8"))["strict_validation"] is True
    )
    DAGManager.load(str(dag_path)).validate_intent_ir(require_all=True)


def test_cli_reports_committed_migration_when_result_write_fails(
    tmp_path,
    monkeypatch,
):
    dag_path = _write_project(tmp_path)
    plan_path = tmp_path / "migration-plan.json"
    result_path = tmp_path / "migration-result.json"
    plan_path.write_text(
        json.dumps(_plan(LegacyIntentMigrator(tmp_path))),
        encoding="utf-8",
    )

    def fail_result_write(*_args, **_kwargs):
        raise OSError("simulated result persistence failure")

    monkeypatch.setattr(
        "aio_agentic_sdlc.dag_cli._write_intent_migration_artifact",
        fail_result_write,
    )

    result = CliRunner().invoke(
        cli,
        [
            "intent",
            "apply-migration",
            "--project-path",
            str(tmp_path),
            "--plan-file",
            str(plan_path),
            "--output",
            str(result_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "migration committed successfully" in result.output
    assert "result evidence could not be saved" in result.output
    assert '"migrated_nodes": 1' in result.output
    assert not result_path.exists()
    DAGManager.load(str(dag_path)).validate_intent_ir(require_all=True)


def test_cli_refuses_to_overwrite_canonical_state_with_inventory(tmp_path):
    dag_path = _write_project(tmp_path)
    before = dag_path.read_bytes()

    result = CliRunner().invoke(
        cli,
        [
            "intent",
            "inventory",
            "--project-path",
            str(tmp_path),
            "--output",
            str(Path(tmp_path) / INTENTION_DAG_FILE),
        ],
    )

    assert result.exit_code == 1
    assert "Refusing to overwrite protected framework state" in result.output
    assert dag_path.read_bytes() == before


@pytest.mark.parametrize("target", ["intention", "plan"])
def test_cli_rejects_protected_apply_output_before_mutating_intent(tmp_path, target):
    dag_path = _write_project(tmp_path)
    plan_path = tmp_path / "migration-plan.json"
    plan_path.write_text(
        json.dumps(_plan(LegacyIntentMigrator(tmp_path))),
        encoding="utf-8",
    )
    output = dag_path if target == "intention" else plan_path
    before_dag = dag_path.read_bytes()
    before_plan = plan_path.read_bytes()

    result = CliRunner().invoke(
        cli,
        [
            "intent",
            "apply-migration",
            "--project-path",
            str(tmp_path),
            "--plan-file",
            str(plan_path),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 1
    assert "Refusing to overwrite protected framework state" in result.output
    assert dag_path.read_bytes() == before_dag
    assert plan_path.read_bytes() == before_plan


def test_cli_rejects_symlinked_result_output_before_mutating_intent(tmp_path):
    dag_path = _write_project(tmp_path)
    plan_path = tmp_path / "migration-plan.json"
    plan_path.write_text(
        json.dumps(_plan(LegacyIntentMigrator(tmp_path))),
        encoding="utf-8",
    )
    external = tmp_path / "external.json"
    external.write_text("preserve me\n", encoding="utf-8")
    result_link = tmp_path / "migration-result.json"
    try:
        result_link.symlink_to(external)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")
    dag_before = dag_path.read_bytes()
    external_before = external.read_bytes()

    result = CliRunner().invoke(
        cli,
        [
            "intent",
            "apply-migration",
            "--project-path",
            str(tmp_path),
            "--plan-file",
            str(plan_path),
            "--output",
            str(result_link),
        ],
    )

    assert result.exit_code == 1
    assert "regular file" in result.output
    assert dag_path.read_bytes() == dag_before
    assert external.read_bytes() == external_before


def test_cli_inventory_rejects_symlinked_output_parent(tmp_path):
    _write_project(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    output_parent = tmp_path / "redirected"
    try:
        output_parent.symlink_to(external, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlink creation unavailable: {error}")

    result = CliRunner().invoke(
        cli,
        [
            "intent",
            "inventory",
            "--project-path",
            str(tmp_path),
            "--output",
            str(output_parent / "coverage.json"),
        ],
    )

    assert result.exit_code == 1
    assert "real directory" in result.output
    assert list(external.iterdir()) == []
