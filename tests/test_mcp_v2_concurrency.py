import asyncio
import hashlib
import json
import os
import stat
import threading
from pathlib import Path

import numpy as np
import pytest
from mcp.client import Client

from aio_agentic_sdlc import core
from aio_agentic_sdlc import mcp_server as mcp_server_module
from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Metadata, Node, NodeType
from aio_agentic_sdlc.intent_ir import IntentIR
from aio_agentic_sdlc.mcp_server import mcp
from aio_agentic_sdlc.workspace import (
    AUDIT_FILE,
    BACKLOG_FILE,
    CHANGES_DIR,
    INTENTION_DAG_FILE,
    MAPPING_LOCK_FILE,
    REALITY_DAG_FILE,
    SPECS_DIR,
    ensure_workspace,
)


def _tool_text(result) -> str:
    return "".join(block.text for block in result.content if hasattr(block, "text"))


def _prd_data(label: str) -> dict[str, str]:
    return {
        key: label
        for key in (
            "title",
            "author",
            "date",
            "introduction",
            "objectives",
            "scope",
            "requirements",
            "user_stories",
            "success_metrics",
            "dependencies",
            "non_functional_requirements",
            "out_of_scope",
            "viability_research",
            "changelog",
        )
    }


def _mapping_intent() -> IntentIR:
    return IntentIR.model_validate(
        {
            "schema_version": 1,
            "provenance": [
                {
                    "source_type": "human_statement",
                    "reference": "test:mcp-v2-concurrency",
                    "statement": "Map one exact source identity once.",
                }
            ],
            "assumptions": [],
            "ambiguities": [],
            "confidence": 1.0,
            "acceptance_criteria": [
                {
                    "id": "TEST-MAP-AC1",
                    "statement": "Only one approval changes the source.",
                    "required_evidence": ["test:concurrent-approval"],
                }
            ],
            "revision_history": [
                {
                    "revision": 1,
                    "recorded_at": "2026-08-20T10:00:00-04:00",
                    "actor": "test",
                    "generator_version": "test/v1",
                    "summary": "Captured the concurrent approval contract.",
                }
            ],
            "responsible_agent": "test",
            "generator_version": "test/v1",
            "approval": {
                "state": "approved",
                "approved_by": "test",
                "approved_at": "2026-08-20T10:00:00-04:00",
                "rationale": "Concurrency fixture.",
            },
        }
    )


@pytest.mark.asyncio
async def test_concurrent_v2_backlog_mutations_do_not_lose_updates(
    tmp_path, monkeypatch
):
    original_load = core.load_backlog
    simultaneous_loads = threading.Barrier(2)

    def synchronized_load(project_path="."):
        data = original_load(project_path)
        simultaneous_loads.wait(timeout=5)
        return data

    monkeypatch.setattr(core, "load_backlog", synchronized_load)
    arguments = {
        "impact": 3,
        "effort": 2,
        "category": "Platform",
        "description": "Exercise the SDK v2 worker-thread mutation boundary.",
        "project_path": str(tmp_path),
    }

    async with Client(mcp, raise_exceptions=True) as client:
        first, second = await asyncio.gather(
            client.call_tool("add_task", {**arguments, "name": "First"}),
            client.call_tool("add_task", {**arguments, "name": "Second"}),
        )

    assert "added successfully" in _tool_text(first)
    assert "added successfully" in _tool_text(second)
    backlog = json.loads((tmp_path / BACKLOG_FILE).read_text(encoding="utf-8"))
    assert backlog["revision"] == 2
    assert set(backlog["nodes"]) == {"First", "Second"}
    audit = [
        json.loads(line)
        for line in (tmp_path / AUDIT_FILE).read_text(encoding="utf-8").splitlines()
    ]
    assert [event["phase"] for event in audit] == [
        "prepared",
        "committed",
        "prepared",
        "committed",
    ]


@pytest.mark.asyncio
async def test_concurrent_v2_backlog_stress_preserves_every_transaction(tmp_path):
    arguments = {
        "impact": 3,
        "effort": 2,
        "category": "Platform",
        "description": "Exercise stable Windows lock-file identities.",
        "project_path": str(tmp_path),
    }

    async with Client(mcp, raise_exceptions=True) as client:
        results = await asyncio.gather(
            *(
                client.call_tool("add_task", {**arguments, "name": f"Task-{index:02d}"})
                for index in range(20)
            )
        )

    assert all(result.is_error is not True for result in results)
    assert all("added successfully" in _tool_text(result) for result in results)
    backlog = json.loads((tmp_path / BACKLOG_FILE).read_text(encoding="utf-8"))
    assert backlog["revision"] == 20
    assert set(backlog["nodes"]) == {f"Task-{index:02d}" for index in range(20)}
    events = [
        json.loads(line)
        for line in (tmp_path / AUDIT_FILE).read_text(encoding="utf-8").splitlines()
    ]
    assert sum(event["phase"] == "prepared" for event in events) == 20
    assert sum(event["phase"] == "committed" for event in events) == 20


@pytest.mark.asyncio
async def test_concurrent_v2_semantic_cache_calls_are_serialized(tmp_path, monkeypatch):
    ensure_workspace(tmp_path)
    spec = tmp_path / SPECS_DIR / "existing.md"
    spec.write_text("A deterministic accepted product requirement.", encoding="utf-8")

    class DeterministicModel:
        def encode(self, texts):
            return np.ones((len(texts), 384), dtype=np.float32)

    monkeypatch.setattr(
        "aio_agentic_sdlc.semantic_dedup.get_model",
        lambda: DeterministicModel(),
    )
    starting_cwd = os.getcwd()
    arguments = {
        "proposed_content": "A deterministic accepted product requirement.",
        "project_path": str(tmp_path),
    }

    async with Client(mcp, raise_exceptions=True) as client:
        results = await asyncio.gather(
            *(client.call_tool("check_duplicate_prd", arguments) for _ in range(4))
        )

    assert all("existing.md" in _tool_text(result) for result in results)
    assert os.getcwd() == starting_cwd
    assert (tmp_path / ".aio-agentic-sdlc" / "semantic-cache.db").is_file()


@pytest.mark.asyncio
async def test_concurrent_v2_mapping_approvals_commit_one_exact_receipt(tmp_path):
    starting_cwd = Path.cwd()
    ensure_workspace(tmp_path)
    intent_id = "00000000-0000-0000-0000-0000000000a4"
    source = tmp_path / "src" / "mapping_component.py"
    source.parent.mkdir()
    original_source = b"class MappingComponent:\n    pass\n"
    source.write_bytes(original_source)
    intention_path = tmp_path / INTENTION_DAG_FILE
    DAGManager(
        Metadata(name="Mapping concurrency", version="1.0"),
        [
            Node(
                id=intent_id,
                type=NodeType.COMPONENT,
                name="MappingComponent",
                intent=_mapping_intent(),
            )
        ],
        [],
    ).save(str(intention_path))
    intention_before = intention_path.read_bytes()

    async with Client(mcp, raise_exceptions=True) as client:
        review_result = await client.call_tool(
            "review_mapping",
            {"intent_id": intent_id, "project_path": str(tmp_path)},
        )
        review = json.loads(_tool_text(review_result))
        candidate_id = review["candidates"][0]["reality"]["id"]
        arguments = {
            "intent_id": intent_id,
            "candidate_reality_id": candidate_id,
            "evidence_digest": review["evidence_digest"],
            "approved_by": "test",
            "approved_at": "2026-08-20T10:00:00-04:00",
            "rationale": "Approve the exact reviewed candidate once.",
            "project_path": str(tmp_path),
        }
        results = await asyncio.gather(
            client.call_tool("approve_mapping", arguments),
            client.call_tool("approve_mapping", arguments),
        )

    successful = [result for result in results if result.is_error is not True]
    rejected = [result for result in results if result.is_error is True]
    assert len(successful) == 1
    assert len(rejected) == 1
    receipt_result = json.loads(_tool_text(successful[0]))
    assert receipt_result["postcondition"]["classification"] == "confirmed"
    assert _tool_text(rejected[0]) == (
        "Error approving mapping: mapping approval requires one unique candidate"
    )

    lines = source.read_text(encoding="utf-8").splitlines()
    assert sum(line.startswith("# aio-sdlc-mapping-approval: ") for line in lines) == 1
    assert lines.count(f"# aio-sdlc-node: {intent_id}") == 1
    receipt = json.loads(lines[0].removeprefix("# aio-sdlc-mapping-approval: "))
    assert receipt["intent_id"] == intent_id
    assert receipt["candidate_reality_id"] == candidate_id
    assert receipt["evidence_digest"] == review["evidence_digest"]
    assert lines[2:] == original_source.decode("utf-8").splitlines()
    assert intention_path.read_bytes() == intention_before
    assert not (tmp_path / REALITY_DAG_FILE).exists()
    assert not (tmp_path / ".aio-agentic-sdlc" / "semantic-cache.db").exists()
    mapping_lock = tmp_path / MAPPING_LOCK_FILE
    assert mapping_lock.is_file()
    assert not mapping_lock.is_symlink()
    assert Path.cwd() == starting_cwd


@pytest.mark.asyncio
async def test_concurrent_v2_mapping_receipt_refreshes_commit_one_transition(
    tmp_path,
):
    starting_cwd = Path.cwd()
    ensure_workspace(tmp_path)
    intent_id = "00000000-0000-0000-0000-0000000000a5"
    candidate_id = "12345678-1234-5678-9234-567812345678"
    source = tmp_path / "src" / "confirmed_component.py"
    source.parent.mkdir()
    neutral = b"class ConfirmedComponent:\n    pass\n"
    receipt = {
        "schema_version": 1,
        "intent_id": intent_id,
        "candidate_reality_id": candidate_id,
        "source_path": "src/confirmed_component.py",
        "symbol_kind": "class",
        "symbol_name": "ConfirmedComponent",
        "source_sha256": hashlib.sha256(neutral).hexdigest(),
        "evidence_digest": "a" * 64,
        "approved_by": "test",
        "approved_at": "2026-08-20T10:00:00-04:00",
        "rationale": "Approve the original exact identity.",
    }
    source.write_bytes(
        (
            "# aio-sdlc-mapping-approval: "
            + json.dumps(receipt, sort_keys=True, separators=(",", ":"))
            + "\n"
            + f"# aio-sdlc-node: {intent_id}\n"
        ).encode()
        + neutral
    )
    intention_path = tmp_path / INTENTION_DAG_FILE
    DAGManager(
        Metadata(name="Receipt concurrency", version="1.0"),
        [
            Node(
                id=intent_id,
                type=NodeType.COMPONENT,
                name="ConfirmedComponent",
                intent=_mapping_intent(),
            )
        ],
        [],
    ).save(str(intention_path))
    intention_before = intention_path.read_bytes()

    async with Client(mcp, raise_exceptions=True) as client:
        review_result = await client.call_tool(
            "review_mapping_receipt",
            {"intent_id": intent_id, "project_path": str(tmp_path)},
        )
        review = json.loads(_tool_text(review_result))
        arguments = {
            "intent_id": intent_id,
            "evidence_digest": review["evidence_digest"],
            "approved_by": "test",
            "approved_at": "2026-08-21T10:00:00-04:00",
            "rationale": "Refresh the exact reviewed receipt once.",
            "project_path": str(tmp_path),
        }
        results = await asyncio.gather(
            client.call_tool("refresh_mapping_receipt", arguments),
            client.call_tool("refresh_mapping_receipt", arguments),
        )

    successful = [result for result in results if result.is_error is not True]
    rejected = [result for result in results if result.is_error is True]
    assert len(successful) == 1
    assert len(rejected) == 1
    refreshed = json.loads(_tool_text(successful[0]))
    assert refreshed["receipt"]["schema_version"] == 2
    assert refreshed["receipt"]["identity_approval"] == receipt
    assert refreshed["postcondition"]["classification"] == "confirmed"
    assert _tool_text(rejected[0]) == (
        "Error refreshing mapping receipt: stale receipt evidence digest"
    )
    content = source.read_bytes()
    assert content.count(b"aio-sdlc-node:") == 1
    assert content.count(b"aio-sdlc-mapping-approval:") == 1
    compile(content, str(source), "exec")
    assert intention_path.read_bytes() == intention_before
    assert not (tmp_path / REALITY_DAG_FILE).exists()
    assert not (tmp_path / ".aio-agentic-sdlc" / "semantic-cache.db").exists()
    mapping_lock = tmp_path / MAPPING_LOCK_FILE
    assert mapping_lock.is_file()
    assert not mapping_lock.is_symlink()
    assert Path.cwd() == starting_cwd


@pytest.mark.asyncio
async def test_concurrent_v2_first_document_generation_creates_workspace_once(tmp_path):
    for attempt in range(12):
        project = tmp_path / f"document-race-{attempt}"
        project.mkdir()
        arguments = {
            "template_name": "prd-template.md",
            "data_json": json.dumps(_prd_data(str(attempt))),
            "output_filename": "same.md",
            "project_path": str(project),
        }

        async with Client(mcp, raise_exceptions=True) as client:
            results = await asyncio.gather(
                client.call_tool("generate_document", arguments),
                client.call_tool("generate_document", arguments),
            )

        assert all(result.is_error is not True for result in results)
        assert all("successfully generated" in _tool_text(result) for result in results)
        assert (project / CHANGES_DIR / "same.md").is_file()


@pytest.mark.asyncio
async def test_concurrent_v2_spec_promotions_are_one_atomic_transition(tmp_path):
    ensure_workspace(tmp_path)
    source = tmp_path / CHANGES_DIR / "accepted.md"
    source.write_text("# Accepted\n", encoding="utf-8")
    arguments = {"feature_name": "accepted.md", "project_path": str(tmp_path)}

    async with Client(mcp, raise_exceptions=True) as client:
        results = await asyncio.gather(
            client.call_tool("promote_spec", arguments),
            client.call_tool("promote_spec", arguments),
        )

    messages = [_tool_text(result) for result in results]
    assert sum("Successfully promoted" in message for message in messages) == 1
    assert sum("not found" in message for message in messages) == 1
    assert not source.exists()
    assert (tmp_path / SPECS_DIR / "accepted.md").read_text(encoding="utf-8") == (
        "# Accepted\n"
    )


@pytest.mark.asyncio
async def test_v2_spec_promotion_rejects_source_leaf_swap_without_external_read(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    ensure_workspace(project)
    source = project / CHANGES_DIR / "accepted.md"
    source.write_text("# Accepted\n", encoding="utf-8")
    destination = project / SPECS_DIR / "accepted.md"
    external = tmp_path / "external.md"
    external.write_text("external-secret\n", encoding="utf-8")
    original_replace = os.replace
    external_read = False

    def swapping_replace(src, dst):
        if Path(dst) == destination:
            source.unlink()
            os.symlink(external, source)
        return original_replace(src, dst)

    def reject_external_read(*_args, **_kwargs):
        nonlocal external_read
        external_read = True
        raise AssertionError("promotion followed the swapped external source")

    monkeypatch.setattr(mcp_server_module.os, "replace", swapping_replace)
    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        if path == external:
            return reject_external_read(*args, **kwargs)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    async with Client(mcp) as client:
        result = await client.call_tool(
            "promote_spec",
            {"feature_name": "accepted.md", "project_path": str(project)},
        )
    monkeypatch.setattr(Path, "open", original_open)

    assert result.is_error is True
    assert _tool_text(result).startswith("Error promoting spec:")
    assert destination.is_symlink() is False
    assert destination.exists() is False
    assert external_read is False
    assert external.read_text(encoding="utf-8") == "external-secret\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("swap_after_replace", [False, True])
async def test_v2_spec_promotion_never_leaves_a_swapped_destination_leaf(
    tmp_path, monkeypatch, swap_after_replace
):
    project = tmp_path / "project"
    project.mkdir()
    ensure_workspace(project)
    source = project / CHANGES_DIR / "accepted.md"
    source.write_text("# Accepted\n", encoding="utf-8")
    destination = project / SPECS_DIR / "accepted.md"
    external = tmp_path / "external.md"
    external.write_text("external-secret\n", encoding="utf-8")
    original_replace = os.replace

    def swapping_replace(src, dst):
        if Path(dst) != destination:
            return original_replace(src, dst)
        if not swap_after_replace:
            os.symlink(external, destination)
        result = original_replace(src, dst)
        if swap_after_replace:
            destination.unlink()
            os.symlink(external, destination)
        return result

    monkeypatch.setattr(mcp_server_module.os, "replace", swapping_replace)
    async with Client(mcp) as client:
        result = await client.call_tool(
            "promote_spec",
            {"feature_name": "accepted.md", "project_path": str(project)},
        )

    assert destination.is_symlink() is False
    assert external.read_text(encoding="utf-8") == "external-secret\n"
    if swap_after_replace:
        assert result.is_error is True
        assert destination.exists() is False
    else:
        assert result.is_error is not True
        assert destination.read_text(encoding="utf-8") == "# Accepted\n"


@pytest.mark.asyncio
async def test_v2_spec_promotion_detects_swap_after_first_destination_postcheck(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    ensure_workspace(project)
    source = project / CHANGES_DIR / "accepted.md"
    source.write_text("# Accepted\n", encoding="utf-8")
    destination = project / SPECS_DIR / "accepted.md"
    external = tmp_path / "external.md"
    external.write_text("external-secret\n", encoding="utf-8")
    original_guard = mcp_server_module.guarded_file_path
    swapped = False

    def swapping_guard(path, *args, **kwargs):
        nonlocal swapped
        guarded = original_guard(path, *args, **kwargs)
        if Path(path) == destination and destination.exists() and not swapped:
            swapped = True
            destination.unlink()
            os.symlink(external, destination)
        return guarded

    monkeypatch.setattr(mcp_server_module, "guarded_file_path", swapping_guard)
    async with Client(mcp) as client:
        result = await client.call_tool(
            "promote_spec",
            {"feature_name": "accepted.md", "project_path": str(project)},
        )

    assert swapped is True
    assert result.is_error is True
    assert destination.is_symlink() is False
    assert source.read_text(encoding="utf-8") == "# Accepted\n"
    assert external.read_text(encoding="utf-8") == "external-secret\n"


@pytest.mark.asyncio
async def test_v2_spec_promotion_preserves_read_only_source_mode(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    ensure_workspace(project)
    source = project / CHANGES_DIR / "accepted.md"
    source.write_text("# Accepted read-only\n", encoding="utf-8")
    source.chmod(stat.S_IREAD)
    destination = project / SPECS_DIR / "accepted.md"
    external = tmp_path / "external.md"
    external.write_text("external-unchanged\n", encoding="utf-8")

    try:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "promote_spec",
                {"feature_name": "accepted.md", "project_path": str(project)},
            )

        assert result.is_error is not True
        assert not source.exists()
        assert destination.read_text(encoding="utf-8") == "# Accepted read-only\n"
        assert stat.S_IMODE(destination.stat().st_mode) & stat.S_IWRITE == 0
        assert external.read_text(encoding="utf-8") == "external-unchanged\n"
    finally:
        if destination.exists():
            destination.chmod(stat.S_IREAD | stat.S_IWRITE)
        if source.exists():
            source.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.asyncio
async def test_v2_spec_promotion_restores_read_only_source_after_late_failure(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    ensure_workspace(project)
    source = project / CHANGES_DIR / "accepted.md"
    source.write_text("# Accepted read-only\n", encoding="utf-8")
    source.chmod(stat.S_IREAD)
    destination = project / SPECS_DIR / "accepted.md"
    external = tmp_path / "external.md"
    external.write_text("external-unchanged\n", encoding="utf-8")
    original_unlink = os.unlink

    def fail_after_source_removal(path, *args, **kwargs):
        result = original_unlink(path, *args, **kwargs)
        if Path(path) == source:
            destination.unlink()
            os.symlink(external, destination)
        return result

    monkeypatch.setattr(mcp_server_module.os, "unlink", fail_after_source_removal)
    try:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "promote_spec",
                {"feature_name": "accepted.md", "project_path": str(project)},
            )

        assert result.is_error is True
        assert source.read_text(encoding="utf-8") == "# Accepted read-only\n"
        assert stat.S_IMODE(source.stat().st_mode) & stat.S_IWRITE == 0
        assert destination.is_symlink() is False
        assert destination.exists() is False
        assert external.read_text(encoding="utf-8") == "external-unchanged\n"
    finally:
        if destination.exists():
            destination.chmod(stat.S_IREAD | stat.S_IWRITE)
        if source.exists():
            source.chmod(stat.S_IREAD | stat.S_IWRITE)
