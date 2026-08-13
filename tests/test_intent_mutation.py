import json
from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner

from aio_agentic_sdlc.dag_cli import cli
from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Metadata, Node, NodeType
from aio_agentic_sdlc.intent_ir import IntentIR
from aio_agentic_sdlc.intent_store import create_intent_node_file, update_intent_file
from aio_agentic_sdlc.mcp_server import (
    create_intent_node,
    review_intent,
    set_intent,
    validate_intent,
)
from aio_agentic_sdlc.workspace import INTENTION_DAG_FILE
from tests.test_intent_ir import NODE_ID, _intent_ir


def _write_legacy_dag(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    DAGManager(
        Metadata(name="Intent", version="1.0"),
        [Node(id=NODE_ID, type=NodeType.COMPONENT, name="Rate limiter")],
        [],
    ).save(str(path))


def _revision_two() -> IntentIR:
    data = _intent_ir().model_dump()
    data["assumptions"].append("Limits are scoped by account ID.")
    data["revision_history"].append(
        {
            "revision": 2,
            "recorded_at": datetime(2026, 7, 23, tzinfo=timezone.utc)
            + timedelta(minutes=5),
            "actor": "sdlc_cartographer",
            "generator_version": "aio-agentic-sdlc/0.23",
            "summary": "Clarified the rate-limit key.",
        }
    )
    data["responsible_agent"] = "sdlc_cartographer"
    return IntentIR.model_validate(data)


def test_update_intent_file_creates_and_revises_with_expected_revision(tmp_path):
    path = tmp_path / "intention-dag.yaml"
    _write_legacy_dag(path)

    update_intent_file(path, NODE_ID, _intent_ir(), expected_revision=0)
    update_intent_file(path, NODE_ID, _revision_two(), expected_revision=1)

    intent = DAGManager.load(str(path)).get_node(NODE_ID).intent
    assert intent.revision_history[-1].revision == 2
    assert intent.assumptions[-1] == "Limits are scoped by account ID."


def test_create_intent_node_file_adds_node_and_payload_atomically(tmp_path):
    path = tmp_path / "intention-dag.yaml"
    DAGManager(Metadata(name="Intent", version="1.0"), [], []).save(str(path))
    node = Node(
        id=NODE_ID,
        type=NodeType.COMPONENT,
        name="Rate limiter",
        intent=_intent_ir(),
    )

    create_intent_node_file(path, node)

    stored = DAGManager.load(str(path)).get_node(NODE_ID)
    assert stored.name == "Rate limiter"
    assert stored.intent == _intent_ir()


def test_create_intent_node_file_requires_intent_payload(tmp_path):
    path = tmp_path / "intention-dag.yaml"
    DAGManager(Metadata(name="Intent", version="1.0"), [], []).save(str(path))

    with pytest.raises(ValueError, match="requires Intent IR"):
        create_intent_node_file(
            path,
            Node(id=NODE_ID, type=NodeType.COMPONENT, name="Rate limiter"),
        )


def test_create_intent_node_file_requires_exactly_initial_revision(tmp_path):
    path = tmp_path / "intention-dag.yaml"
    DAGManager(Metadata(name="Intent", version="1.0"), [], []).save(str(path))

    with pytest.raises(ValueError, match="exactly revision 1"):
        create_intent_node_file(
            path,
            Node(
                id=NODE_ID,
                type=NodeType.COMPONENT,
                name="Rate limiter",
                intent=_revision_two(),
            ),
        )


def test_update_intent_file_rejects_stale_writer(tmp_path):
    path = tmp_path / "intention-dag.yaml"
    _write_legacy_dag(path)
    update_intent_file(path, NODE_ID, _intent_ir(), expected_revision=0)

    with pytest.raises(ValueError, match="stale Intent IR revision"):
        update_intent_file(path, NODE_ID, _revision_two(), expected_revision=0)


def test_update_intent_file_rejects_history_rewrite(tmp_path):
    path = tmp_path / "intention-dag.yaml"
    _write_legacy_dag(path)
    update_intent_file(path, NODE_ID, _intent_ir(), expected_revision=0)
    rewritten = _revision_two().model_dump()
    rewritten["revision_history"][0]["summary"] = "Rewritten history."

    with pytest.raises(ValueError, match="preserve existing revision history"):
        update_intent_file(
            path,
            NODE_ID,
            IntentIR.model_validate(rewritten),
            expected_revision=1,
        )


def test_update_intent_file_preserves_original_on_replace_failure(
    tmp_path, monkeypatch
):
    path = tmp_path / "intention-dag.yaml"
    _write_legacy_dag(path)
    before = path.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("aio_agentic_sdlc.dag_manager.os.replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        update_intent_file(path, NODE_ID, _intent_ir(), expected_revision=0)

    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".intention-dag.yaml.*.tmp"))


def test_intent_cli_sets_payload_from_json_file(tmp_path):
    dag_path = tmp_path / "intention-dag.yaml"
    payload_path = tmp_path / "intent.json"
    _write_legacy_dag(dag_path)
    payload_path.write_text(_intent_ir().model_dump_json(indent=2), encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "intent",
            "set",
            "--file",
            str(dag_path),
            "--node-id",
            NODE_ID,
            "--payload-file",
            str(payload_path),
            "--expected-revision",
            "0",
        ],
    )

    assert result.exit_code == 0
    assert "revision 1" in result.output
    assert DAGManager.load(str(dag_path)).get_node(NODE_ID).intent is not None


def test_intent_cli_creates_node_with_payload(tmp_path):
    dag_path = tmp_path / "intention-dag.yaml"
    payload_path = tmp_path / "intent.json"
    DAGManager(Metadata(name="Intent", version="1.0"), [], []).save(str(dag_path))
    payload_path.write_text(_intent_ir().model_dump_json(indent=2), encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "intent",
            "create-node",
            "--file",
            str(dag_path),
            "--node-id",
            NODE_ID,
            "--type",
            "component",
            "--name",
            "Rate limiter",
            "--payload-file",
            str(payload_path),
        ],
    )

    assert result.exit_code == 0
    assert "created with Intent IR revision 1" in result.output


def test_mcp_intent_tools_use_project_path_and_protected_file(tmp_path):
    dag_path = tmp_path / INTENTION_DAG_FILE
    _write_legacy_dag(dag_path)

    write_result = set_intent(
        node_id=NODE_ID,
        payload_json=_intent_ir().model_dump_json(),
        expected_revision=0,
        project_path=str(tmp_path),
    )
    validation_result = validate_intent(project_path=str(tmp_path), require_all=True)
    review_result = review_intent(project_path=str(tmp_path), node_id=NODE_ID)

    assert "revision 1" in write_result
    assert validation_result == "Intent IR validation passed."
    assert "Rate limiter" in review_result
    assert "chat:turn-42" in review_result


def test_mcp_create_intent_node_uses_canonical_project_dag(tmp_path):
    dag_path = tmp_path / INTENTION_DAG_FILE
    dag_path.parent.mkdir(parents=True)
    DAGManager(Metadata(name="Intent", version="1.0"), [], []).save(str(dag_path))

    result = create_intent_node(
        node_id=NODE_ID,
        node_type="component",
        name="Rate limiter",
        domain="security",
        description="Limits password-reset requests.",
        payload_json=_intent_ir().model_dump_json(),
        project_path=str(tmp_path),
    )

    assert "created with Intent IR revision 1" in result
    assert DAGManager.load(str(dag_path)).get_node(NODE_ID).domain == "security"


def test_mcp_set_intent_rejects_invalid_json_without_mutation(tmp_path):
    dag_path = tmp_path / INTENTION_DAG_FILE
    _write_legacy_dag(dag_path)
    before = dag_path.read_bytes()

    result = set_intent(
        node_id=NODE_ID,
        payload_json=json.dumps({"confidence": 4}),
        expected_revision=0,
        project_path=str(tmp_path),
    )

    assert result.startswith("Error setting Intent IR:")
    assert dag_path.read_bytes() == before
