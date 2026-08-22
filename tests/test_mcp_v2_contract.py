import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest
from mcp import MCPError, StdioServerParameters, stdio_client
from mcp.client import Client

from aio_agentic_sdlc import mcp_server as mcp_server_module
from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Metadata, Node, NodeType
from aio_agentic_sdlc.mcp_server import mcp
from aio_agentic_sdlc.reality_dag_generator import RealityDAGGenerator
from aio_agentic_sdlc.workspace import (
    AUDIT_FILE,
    BACKLOG_FILE,
    CHANGES_DIR,
    CONFIG_FILE,
    INTENTION_DAG_FILE,
    MAPPING_LOCK_FILE,
    REALITY_DAG_FILE,
    STATE_LOCK_FILE,
    WORKSPACE_MIGRATION_LOCK_FILE,
    ensure_workspace,
)

EXPECTED_TOOLS = {
    "add_task",
    "approve_mapping",
    "block_task",
    "check_duplicate_prd",
    "create_intent_node",
    "generate_document",
    "generate_reality",
    "get_next_task",
    "prioritize_backlog",
    "promote_spec",
    "reconcile_dags",
    "remove_task",
    "review_intent",
    "review_mapping",
    "review_mapping_receipt",
    "refresh_mapping_receipt",
    "set_intent",
    "triage_reconciliation_drift",
    "update_task",
    "update_task_status",
    "validate_intent",
    "validate_traceability",
    "visualize_dag",
}
EXPECTED_RESOURCES = {"backlog://current", "backlog://hierarchy-rules"}
EXPECTED_PROMPTS = {"pick-next-task"}
EXPECTED_RESOURCE_DESCRIPTIONS = {
    "backlog://current": (
        "Read the complete prioritized project backlog as JSON from the current "
        "working directory."
    ),
    "backlog://hierarchy-rules": "Read the validation mode and graph hierarchy rules.",
}
EXPECTED_PROMPT_DESCRIPTIONS = {
    "pick-next-task": "Prompt the agent to pick the next workable task from the backlog."
}

EXPECTED_TOOL_DESCRIPTIONS = {
    "add_task": "Add a new task to the project backlog.",
    "approve_mapping": "Approve one fresh candidate and atomically persist verified source evidence.",
    "block_task": "Add a blocker to a task, preventing it from being worked on.",
    "check_duplicate_prd": "Check if a proposed PRD is similar to canonical project specs.",
    "create_intent_node": "Atomically create a canonical node with its initial Intent IR payload.",
    "generate_document": "Generate a document from a template using the provided data.",
    "generate_reality": "Scan the codebase and update the Reality DAG via dag-tool.",
    "get_next_task": "Find and return the highest-priority workable task from the backlog.",
    "prioritize_backlog": "Force an immediate topological sort and priority re-calculation of the backlog.",
    "promote_spec": "Move a validated micro-spec from changes to canonical specs.",
    "reconcile_dags": "Classify Intention/Reality identity evidence without mutating project state.",
    "remove_task": "Remove a task entirely from the backlog.",
    "review_intent": "Render a human-readable review of canonical Intent IR payloads.",
    "review_mapping": "Return a human-first decision brief plus fresh source-bound audit evidence.",
    "review_mapping_receipt": "Review fresh maintenance evidence for one confirmed source receipt.",
    "refresh_mapping_receipt": "Atomically refresh one confirmed source receipt from exact approved evidence.",
    "set_intent": "Create or revise one Intent IR payload with optimistic revision protection.",
    "triage_reconciliation_drift": "Classify safe reconciliation work before backlog execution.",
    "update_task": "Update an existing task in the project backlog.",
    "update_task_status": "Quickly update the status of an existing task.",
    "validate_intent": "Validate Intent IR payloads and coverage in the canonical Intention DAG.",
    "validate_traceability": "Validate that canonical specs align with both DAGs via GUID frontmatter.",
    "visualize_dag": "Render canonical DAG evidence without mutating project state.",
}

INTEGER_ARGUMENTS = {
    "impact",
    "effort",
    "expected_revision",
    "depth",
    "max_items",
    "max_edges",
    "max_candidates",
}
NUMBER_ARGUMENTS = {"similarity_threshold"}
BOOLEAN_ARGUMENTS = {"require_all"}

EXPECTED_ARGUMENT_CONTRACT = {
    "add_task": (
        {"name", "impact", "effort", "category", "description"},
        {
            "requires": "",
            "status": "New",
            "project_path": ".",
            "item_type": "Task",
            "parent_id": None,
        },
    ),
    "approve_mapping": (
        {
            "intent_id",
            "candidate_reality_id",
            "evidence_digest",
            "approved_by",
            "approved_at",
            "rationale",
        },
        {"project_path": ".", "selection_mode": "automatic_name_match"},
    ),
    "block_task": ({"name", "reason"}, {"project_path": "."}),
    "check_duplicate_prd": (
        {"proposed_content"},
        {"project_path": ".", "similarity_threshold": 0.2},
    ),
    "create_intent_node": (
        {"node_id", "node_type", "name", "payload_json"},
        {"domain": None, "description": None, "project_path": "."},
    ),
    "generate_document": (
        {"template_name", "data_json", "output_filename"},
        {"target_dir": CHANGES_DIR, "project_path": "."},
    ),
    "generate_reality": (
        set(),
        {
            "project_path": ".",
            "output": REALITY_DAG_FILE,
            "system": "system_root",
        },
    ),
    "get_next_task": (set(), {"project_path": "."}),
    "prioritize_backlog": (set(), {"project_path": "."}),
    "promote_spec": ({"feature_name"}, {"project_path": "."}),
    "reconcile_dags": (
        set(),
        {"project_path": ".", "max_items": 100, "max_candidates": 20},
    ),
    "remove_task": ({"name"}, {"project_path": "."}),
    "review_intent": (set(), {"project_path": ".", "node_id": None}),
    "review_mapping": (
        {"intent_id"},
        {"candidate_reality_id": None, "project_path": "."},
    ),
    "review_mapping_receipt": ({"intent_id"}, {"project_path": "."}),
    "refresh_mapping_receipt": (
        {
            "intent_id",
            "evidence_digest",
            "approved_by",
            "approved_at",
            "rationale",
        },
        {"project_path": "."},
    ),
    "set_intent": (
        {"node_id", "payload_json", "expected_revision"},
        {"project_path": "."},
    ),
    "triage_reconciliation_drift": (
        set(),
        {"project_path": ".", "decisions_json": "", "max_items": 100},
    ),
    "update_task": (
        {"name"},
        {
            "impact": None,
            "effort": None,
            "category": None,
            "description": None,
            "requires": None,
            "status": None,
            "project_path": ".",
            "item_type": None,
            "parent_id": None,
        },
    ),
    "update_task_status": (
        {"name", "new_status"},
        {"project_path": "."},
    ),
    "validate_intent": (
        set(),
        {"project_path": ".", "require_all": True},
    ),
    "validate_traceability": (set(), {"project_path": "."}),
    "visualize_dag": (
        set(),
        {
            "project_path": ".",
            "view": "comparison",
            "focus_node_id": "",
            "depth": 1,
            "max_items": 100,
            "max_edges": 200,
            "max_candidates": 20,
            "output_format": "human",
        },
    ),
}


def _tool_text(result) -> str:
    return "".join(block.text for block in result.content if hasattr(block, "text"))


PROTECTED_STATE_FILES = (
    INTENTION_DAG_FILE,
    REALITY_DAG_FILE,
    BACKLOG_FILE,
    CONFIG_FILE,
    AUDIT_FILE,
    STATE_LOCK_FILE,
    MAPPING_LOCK_FILE,
    WORKSPACE_MIGRATION_LOCK_FILE,
    ".aio-agentic-sdlc/.intention-dag.yaml.lock",
    ".aio-agentic-sdlc/.reality-dag.yaml.lock",
    ".aio-agentic-sdlc/.spec-promotion.lock",
    ".aio-agentic-sdlc/semantic-cache.db",
    ".aio-agentic-sdlc/semantic-cache.db-journal",
    ".aio-agentic-sdlc/semantic-cache.db-shm",
    ".aio-agentic-sdlc/semantic-cache.db-wal",
    ".aio-agentic-sdlc/semantic-cache.lock",
)


def _seed_protected_state(project: Path) -> dict[str, str]:
    ensure_workspace(project)
    for index, relative in enumerate(PROTECTED_STATE_FILES):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"protected-{index}-{relative}\n".encode())
    return _protected_state_hashes(project)


def _protected_state_hashes(project: Path) -> dict[str, str]:
    return {
        relative: sha256((project / relative).read_bytes()).hexdigest()
        for relative in PROTECTED_STATE_FILES
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_v2_client_discovers_the_complete_public_surface(mode):
    async with Client(mcp, mode=mode, raise_exceptions=True) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        prompts = await client.list_prompts()

    assert {tool.name for tool in tools.tools} == EXPECTED_TOOLS
    assert {str(resource.uri) for resource in resources.resources} == EXPECTED_RESOURCES
    assert {prompt.name for prompt in prompts.prompts} == EXPECTED_PROMPTS
    assert {
        str(resource.uri): resource.description for resource in resources.resources
    } == EXPECTED_RESOURCE_DESCRIPTIONS
    assert {prompt.name: prompt.description for prompt in prompts.prompts} == (
        EXPECTED_PROMPT_DESCRIPTIONS
    )

    for tool in tools.tools:
        required, defaults = EXPECTED_ARGUMENT_CONTRACT[tool.name]
        schema = tool.input_schema
        assert tool.description == EXPECTED_TOOL_DESCRIPTIONS[tool.name]
        assert set(schema.get("required", [])) == required
        assert set(schema["properties"]) == required | set(defaults)
        assert {
            name: schema["properties"][name].get("default") for name in defaults
        } == defaults
        for name, property_schema in schema["properties"].items():
            expected_type = "string"
            if name in INTEGER_ARGUMENTS:
                expected_type = "integer"
            elif name in NUMBER_ARGUMENTS:
                expected_type = "number"
            elif name in BOOLEAN_ARGUMENTS:
                expected_type = "boolean"
            assert property_schema["type"] == expected_type
        assert tool.output_schema["type"] == "object"
        assert tool.output_schema["required"] == ["result"]
        assert tool.output_schema["properties"]["result"]["type"] == "string"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_v2_client_exercises_fixed_resources_and_prompt(
    mode, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    async with Client(mcp, mode=mode, raise_exceptions=True) as client:
        current = await client.read_resource("backlog://current")
        hierarchy = await client.read_resource("backlog://hierarchy-rules")
        prompt = await client.get_prompt("pick-next-task")

    assert json.loads(current.contents[0].text)["nodes"] == {}
    assert "hierarchy" in json.loads(hierarchy.contents[0].text)
    assert "get_next_task" in prompt.messages[0].content.text


@pytest.mark.asyncio
async def test_v2_schema_errors_fail_closed_without_creating_state(tmp_path):
    async with Client(mcp) as client:
        result = await client.call_tool(
            "add_task",
            {
                "name": "Invalid",
                "impact": "not-an-integer",
                "effort": 1,
                "category": "Platform",
                "description": "This request must be rejected by the wire schema.",
                "project_path": str(tmp_path),
            },
        )

    assert result.is_error is True
    assert not (tmp_path / ".aio-agentic-sdlc" / "backlog.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_v2_mapping_review_bounds_hostile_display_fields(mode, tmp_path):
    private_tail = "-PRIVATE-MCP-TAIL"
    hostile = "PRIVATE-MCP-START-" + ("x" * 200_000) + private_tail
    intent_id = "15019926-c6be-5c98-b558-954c7657e5c6"
    source = tmp_path / "src" / "runtime.py"
    source.parent.mkdir()
    source.write_text("class RuntimeBoundary:\n    pass\n", encoding="utf-8")
    intention = tmp_path / INTENTION_DAG_FILE
    intention.parent.mkdir(parents=True)
    DAGManager(
        Metadata(name="Bounded protocol output", version="1.0"),
        [
            Node(
                id=intent_id,
                type=NodeType.COMPONENT,
                name="MCP SDK v2 Integration",
                description=hostile,
            )
        ],
        [],
    ).save(str(intention))
    reality = RealityDAGGenerator(str(tmp_path), "Bounded protocol output").generate()
    observed_id = next(
        node.id for node in reality.nodes.values() if node.name == "RuntimeBoundary"
    )

    async with Client(mcp, mode=mode, raise_exceptions=True) as client:
        result = await client.call_tool(
            "review_mapping",
            {
                "intent_id": intent_id,
                "candidate_reality_id": observed_id,
                "project_path": str(tmp_path),
            },
        )

    text = _tool_text(result)
    report = json.loads(text)
    assert result.is_error is not True
    assert len(text.encode("utf-8")) < 64 * 1024
    assert private_tail not in text
    assert report["decision_brief"]["intention"]["_display_bounds"]["responsibility"][
        "original_chars"
    ] == len(hostile)


@pytest.mark.asyncio
async def test_v2_handler_failures_are_error_results_without_internal_details(
    tmp_path, monkeypatch
):
    def fail_handler(_project_path):
        raise RuntimeError("private-internal-sentinel")

    monkeypatch.setattr(mcp_server_module, "get_next_item", fail_handler)
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_next_task", {"project_path": str(tmp_path)}
        )

    text = _tool_text(result)
    assert result.is_error is True
    assert text == "Tool 'get_next_task' failed."
    assert "private-internal-sentinel" not in text
    assert not (tmp_path / ".aio-agentic-sdlc" / "backlog.json").exists()


@pytest.mark.asyncio
async def test_v2_unexpected_value_error_reaches_the_sanitizing_server(
    tmp_path, monkeypatch
):
    def fail_add_item(**_kwargs):
        raise ValueError("PRIVATE-QA-VALUEERROR")

    monkeypatch.setattr(mcp_server_module, "add_item", fail_add_item)
    async with Client(mcp) as client:
        result = await client.call_tool(
            "add_task",
            {
                "name": "Sentinel",
                "impact": 3,
                "effort": 2,
                "category": "QA",
                "description": "Unexpected ValueError must be sanitized.",
                "project_path": str(tmp_path),
            },
        )

    text = _tool_text(result)
    assert result.is_error is True
    assert text == "Tool 'add_task' failed."
    assert "PRIVATE-QA-VALUEERROR" not in text
    assert not (tmp_path / BACKLOG_FILE).exists()


@pytest.mark.asyncio
async def test_v2_generate_document_unexpected_failure_is_sanitized(
    tmp_path, monkeypatch
):
    before = _seed_protected_state(tmp_path)

    def fail_document(*_args, **_kwargs):
        raise RuntimeError("private-document-sentinel")

    monkeypatch.setattr(
        mcp_server_module, "generate_document_from_template", fail_document
    )
    async with Client(mcp) as client:
        result = await client.call_tool(
            "generate_document",
            {
                "template_name": "prd-template.md",
                "data_json": "{}",
                "output_filename": "failure.md",
                "project_path": str(tmp_path),
            },
        )

    text = _tool_text(result)
    assert result.is_error is True
    assert text == "Tool 'generate_document' failed."
    assert "private-document-sentinel" not in text
    assert _protected_state_hashes(tmp_path) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target_dir", "output_filename"),
    [
        (".aio-agentic-sdlc", "intention-dag.yaml"),
        (".aio-agentic-sdlc/changes/..", "intention-dag.yaml"),
        (".aio-agentic-sdlc", "backlog.json"),
        (".aio-agentic-sdlc", "state-audit.jsonl"),
        (".aio-agentic-sdlc", "mapping.lock"),
        (".aio-agentic-sdlc", "semantic-cache.db-journal"),
        (".aio-agentic-sdlc", "semantic-cache.db-shm"),
        (".aio-agentic-sdlc", "semantic-cache.db-wal"),
    ],
)
async def test_v2_generate_document_rejects_protected_state_aliases_without_mutation(
    tmp_path, monkeypatch, target_dir, output_filename
):
    before = _seed_protected_state(tmp_path)
    generator_called = False

    def unexpected_generator(*_args, **_kwargs):
        nonlocal generator_called
        generator_called = True
        raise AssertionError("protected output reached document generation")

    monkeypatch.setattr(
        mcp_server_module, "generate_document_from_template", unexpected_generator
    )
    async with Client(mcp) as client:
        result = await client.call_tool(
            "generate_document",
            {
                "template_name": "prd-template.md",
                "data_json": "{}",
                "target_dir": target_dir,
                "output_filename": output_filename,
                "project_path": str(tmp_path),
            },
        )

    assert result.is_error is True
    assert "protected project state" in _tool_text(result)
    assert generator_called is False
    assert _protected_state_hashes(tmp_path) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output",
    [
        INTENTION_DAG_FILE,
        ".aio-agentic-sdlc/changes/../intention-dag.yaml",
        BACKLOG_FILE,
        AUDIT_FILE,
        MAPPING_LOCK_FILE,
        ".aio-agentic-sdlc/semantic-cache.db-journal",
        ".aio-agentic-sdlc/semantic-cache.db-shm",
        ".aio-agentic-sdlc/semantic-cache.db-wal",
        "src/reality-dag.yaml",
    ],
)
async def test_v2_generate_reality_rejects_protected_aliases_before_subprocess(
    tmp_path, monkeypatch, output
):
    before = _seed_protected_state(tmp_path)
    subprocess_called = False

    def unexpected_subprocess(*_args, **_kwargs):
        nonlocal subprocess_called
        subprocess_called = True
        raise AssertionError("protected Reality output reached subprocess")

    monkeypatch.setattr("subprocess.run", unexpected_subprocess)
    async with Client(mcp) as client:
        result = await client.call_tool(
            "generate_reality",
            {"project_path": str(tmp_path), "output": output},
        )

    assert result.is_error is True
    assert "protected" in _tool_text(result)
    assert subprocess_called is False
    assert _protected_state_hashes(tmp_path) == before


@pytest.mark.asyncio
async def test_v2_generate_reality_suppresses_untrusted_subprocess_stderr(
    tmp_path, monkeypatch
):
    before = _seed_protected_state(tmp_path)
    output = ".aio-agentic-sdlc/rejected-reality.yaml"

    def failed_subprocess(*args, **_kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=73,
            stdout="",
            stderr="PRIVATE-REALITY-SECRET-" * 10_000,
        )

    monkeypatch.setattr("subprocess.run", failed_subprocess)
    async with Client(mcp) as client:
        result = await client.call_tool(
            "generate_reality",
            {"project_path": str(tmp_path), "output": output},
        )

    text = _tool_text(result)
    assert result.is_error is True
    assert text == (
        "Error generating Reality DAG (Exit Code 73): diagnostic output was suppressed."
    )
    assert "PRIVATE-REALITY-SECRET" not in text
    assert len(text) < 160
    assert not (tmp_path / output).exists()
    assert _protected_state_hashes(tmp_path) == before


@pytest.mark.asyncio
async def test_v2_artifact_handlers_reject_hardlinked_protected_state_aliases(
    tmp_path, monkeypatch
):
    before = _seed_protected_state(tmp_path)
    alias = tmp_path / "state-alias.yaml"
    os.link(tmp_path / INTENTION_DAG_FILE, alias)
    reality_alias = tmp_path / "reality-alias.yaml"
    os.link(tmp_path / REALITY_DAG_FILE, reality_alias)
    document_called = False
    subprocess_called = False

    def unexpected_document(*_args, **_kwargs):
        nonlocal document_called
        document_called = True

    def unexpected_subprocess(*_args, **_kwargs):
        nonlocal subprocess_called
        subprocess_called = True

    monkeypatch.setattr(
        mcp_server_module, "generate_document_from_template", unexpected_document
    )
    monkeypatch.setattr("subprocess.run", unexpected_subprocess)
    async with Client(mcp) as client:
        document = await client.call_tool(
            "generate_document",
            {
                "template_name": "prd-template.md",
                "data_json": "{}",
                "target_dir": ".",
                "output_filename": alias.name,
                "project_path": str(tmp_path),
            },
        )
        reality = await client.call_tool(
            "generate_reality",
            {"project_path": str(tmp_path), "output": reality_alias.name},
        )

    assert document.is_error is True
    assert reality.is_error is True
    assert document_called is False
    assert subprocess_called is False
    assert _protected_state_hashes(tmp_path) == before


@pytest.mark.asyncio
async def test_v2_unknown_resource_uri_is_a_protocol_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    async with Client(mcp) as client:
        with pytest.raises(MCPError):
            await client.read_resource("backlog://unknown")

    assert not (tmp_path / ".aio-agentic-sdlc" / "backlog.json").exists()


@pytest.mark.asyncio
async def test_v2_artifact_handlers_reject_unsafe_paths_before_execution(
    tmp_path, monkeypatch
):
    ensure_workspace(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.yaml"
    outside.write_text("preserve", encoding="utf-8")
    subprocess_called = False

    def unexpected_subprocess(*_args, **_kwargs):
        nonlocal subprocess_called
        subprocess_called = True
        raise AssertionError("unsafe Reality output reached the subprocess")

    monkeypatch.setattr("subprocess.run", unexpected_subprocess)
    async with Client(mcp, raise_exceptions=True) as client:
        reality = await client.call_tool(
            "generate_reality",
            {"project_path": str(tmp_path), "output": "../outside.yaml"},
        )
        promotion = await client.call_tool(
            "promote_spec",
            {"project_path": str(tmp_path), "feature_name": "../outside.md"},
        )

    assert "outside of the project root" in _tool_text(reality)
    assert "without traversal" in _tool_text(promotion)
    assert subprocess_called is False
    assert outside.read_text(encoding="utf-8") == "preserve"


@pytest.mark.asyncio
async def test_real_stdio_entrypoint_serves_the_preserved_surface(tmp_path):
    executable = Path(sys.executable).with_name(
        "aio-agentic-sdlc-mcp.exe" if os.name == "nt" else "aio-agentic-sdlc-mcp"
    )
    assert executable.is_file()
    transport = stdio_client(
        StdioServerParameters(command=str(executable), cwd=tmp_path)
    )

    async with Client(transport, mode="auto", raise_exceptions=True) as client:
        tools = await client.list_tools()
        current = await client.read_resource("backlog://current")

    assert {tool.name for tool in tools.tools} == EXPECTED_TOOLS
    assert json.loads(current.contents[0].text)["nodes"] == {}


def _intent_payload(*, revision: int) -> dict:
    history = [
        {
            "revision": 1,
            "recorded_at": "2026-08-20T10:00:00-04:00",
            "actor": "test",
            "generator_version": "test/v1",
            "summary": "Captured the protocol contract.",
        }
    ]
    if revision == 2:
        history.append(
            {
                "revision": 2,
                "recorded_at": "2026-08-20T10:01:00-04:00",
                "actor": "test",
                "generator_version": "test/v1",
                "summary": "Reconfirmed the protocol contract.",
            }
        )
    return {
        "schema_version": 1,
        "provenance": [
            {
                "source_type": "human_statement",
                "reference": "test:mcp-v2",
                "statement": "Preserve the MCP protocol contract.",
            }
        ],
        "assumptions": [],
        "ambiguities": [],
        "confidence": 1.0,
        "acceptance_criteria": [
            {
                "id": "TEST-AC1",
                "statement": "The protocol call succeeds.",
                "required_evidence": ["test:mcp-v2-contract"],
            }
        ],
        "revision_history": history,
        "responsible_agent": "test",
        "generator_version": "test/v1",
        "approval": {
            "state": "approved",
            "approved_by": "test",
            "approved_at": "2026-08-20T10:00:00-04:00",
            "rationale": "Protocol fixture.",
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_v2_client_exercises_every_published_tool(mode, tmp_path, monkeypatch):
    starting_cwd = Path.cwd()
    ensure_workspace(tmp_path)
    for relative in (INTENTION_DAG_FILE, REALITY_DAG_FILE):
        DAGManager(Metadata(name="MCP v2", version="1.0"), [], []).save(
            str(tmp_path / relative)
        )
    change = tmp_path / CHANGES_DIR / "promote-me.md"
    change.write_text("# Accepted micro-spec\n", encoding="utf-8")
    existing_spec = tmp_path / ".aio-agentic-sdlc" / "specs" / "existing.md"
    existing_spec.write_text("protocol", encoding="utf-8")
    implementation = tmp_path / "src" / "protocol_component.py"
    implementation.parent.mkdir()
    implementation.write_text("class ProtocolComponent:\n    pass\n", encoding="utf-8")

    class DeterministicModel:
        def encode(self, texts):
            return np.ones((len(texts), 384), dtype=np.float32)

    monkeypatch.setattr(
        "aio_agentic_sdlc.semantic_dedup.get_model",
        lambda: DeterministicModel(),
    )

    def generate_valid_reality(arguments, **_kwargs):
        output = Path(arguments[arguments.index("--output") + 1])
        RealityDAGGenerator(str(tmp_path), "MCP v2").generate().save(str(output))
        return subprocess.CompletedProcess(
            args=arguments,
            returncode=0,
            stdout="generated",
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", generate_valid_reality)
    project_path = str(tmp_path)
    node_id = "00000000-0000-0000-0000-0000000000a2"
    prd_data = {
        key: "value"
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

    results = {}

    async with Client(mcp, mode=mode, raise_exceptions=True) as client:

        async def call_success(name, arguments):
            result = await client.call_tool(name, arguments)
            text = _tool_text(result)
            assert result.is_error is not True, (name, result)
            assert text, name
            assert result.structured_content == {"result": text}
            results[name] = result
            return text

        await call_success(
            "add_task",
            {
                "name": "Protocol task",
                "impact": 3,
                "effort": 2,
                "category": "Platform",
                "description": "Exercise the tool contract.",
                "project_path": project_path,
            },
        )
        backlog = json.loads((tmp_path / BACKLOG_FILE).read_text(encoding="utf-8"))
        assert backlog["nodes"]["Protocol task"]["impact"] == 3

        await call_success(
            "update_task",
            {"name": "Protocol task", "impact": 4, "project_path": project_path},
        )
        backlog = json.loads((tmp_path / BACKLOG_FILE).read_text(encoding="utf-8"))
        assert backlog["nodes"]["Protocol task"]["impact"] == 4

        await call_success(
            "update_task_status",
            {
                "name": "Protocol task",
                "new_status": "In Progress",
                "project_path": project_path,
            },
        )
        backlog = json.loads((tmp_path / BACKLOG_FILE).read_text(encoding="utf-8"))
        assert backlog["nodes"]["Protocol task"]["status"] == "In Progress"

        assert "prioritized" in (
            await call_success("prioritize_backlog", {"project_path": project_path})
        )
        next_task = json.loads(
            await call_success("get_next_task", {"project_path": project_path})
        )
        assert next_task["target"]["name"] == "Protocol task"

        await call_success(
            "block_task",
            {"name": "Protocol task", "reason": "test", "project_path": project_path},
        )
        backlog = json.loads((tmp_path / BACKLOG_FILE).read_text(encoding="utf-8"))
        assert backlog["nodes"]["Protocol task"]["blockers"]

        await call_success(
            "generate_document",
            {
                "template_name": "prd-template.md",
                "data_json": json.dumps(prd_data),
                "output_filename": "protocol-prd.md",
                "project_path": project_path,
            },
        )
        generated_document = tmp_path / CHANGES_DIR / "protocol-prd.md"
        assert generated_document.is_file()
        assert "value" in generated_document.read_text(encoding="utf-8")

        duplicate_result = await call_success(
            "check_duplicate_prd",
            {"proposed_content": "protocol", "project_path": project_path},
        )
        assert "existing.md" in duplicate_result

        await call_success(
            "create_intent_node",
            {
                "node_id": node_id,
                "node_type": "component",
                "name": "ProtocolComponent",
                "payload_json": json.dumps(_intent_payload(revision=1)),
                "project_path": project_path,
            },
        )
        intention = DAGManager.load(str(tmp_path / INTENTION_DAG_FILE))
        assert intention.get_node(node_id).intent.revision_history[-1].revision == 1

        await call_success(
            "set_intent",
            {
                "node_id": node_id,
                "payload_json": json.dumps(_intent_payload(revision=2)),
                "expected_revision": 1,
                "project_path": project_path,
            },
        )
        intention = DAGManager.load(str(tmp_path / INTENTION_DAG_FILE))
        assert intention.get_node(node_id).intent.revision_history[-1].revision == 2

        assert (
            await call_success("validate_intent", {"project_path": project_path})
            == "Intent IR validation passed."
        )
        assert "ProtocolComponent" in await call_success(
            "review_intent", {"project_path": project_path, "node_id": node_id}
        )

        review = json.loads(
            await call_success(
                "review_mapping",
                {"intent_id": node_id, "project_path": project_path},
            )
        )
        assert review["classification"] == "candidate"
        assert len(review["candidates"]) == 1
        candidate_id = review["candidates"][0]["reality"]["id"]
        approval = json.loads(
            await call_success(
                "approve_mapping",
                {
                    "intent_id": node_id,
                    "candidate_reality_id": candidate_id,
                    "evidence_digest": review["evidence_digest"],
                    "approved_by": "test",
                    "approved_at": "2026-08-20T10:00:00-04:00",
                    "rationale": "Exercise the validated request schema.",
                    "project_path": project_path,
                },
            )
        )
        assert approval["postcondition"]["classification"] == "confirmed"
        assert f"# aio-sdlc-node: {node_id}" in implementation.read_text(
            encoding="utf-8"
        )

        receipt_review = json.loads(
            await call_success(
                "review_mapping_receipt",
                {"intent_id": node_id, "project_path": project_path},
            )
        )
        assert receipt_review["operation"] == "receipt_refresh"
        receipt_refresh = json.loads(
            await call_success(
                "refresh_mapping_receipt",
                {
                    "intent_id": node_id,
                    "evidence_digest": receipt_review["evidence_digest"],
                    "approved_by": "test",
                    "approved_at": "2026-08-20T10:05:00-04:00",
                    "rationale": "Exercise the receipt refresh request schema.",
                    "project_path": project_path,
                },
            )
        )
        assert receipt_refresh["receipt"]["schema_version"] == 2
        assert receipt_refresh["postcondition"]["classification"] == "confirmed"

        await call_success("generate_reality", {"project_path": project_path})
        reality = DAGManager.load(str(tmp_path / REALITY_DAG_FILE))
        reality.validate()
        assert reality.get_node(node_id).name == "ProtocolComponent"

        reconciliation = json.loads(
            await call_success("reconcile_dags", {"project_path": project_path})
        )
        assert node_id in json.dumps(reconciliation)
        visualization = await call_success(
            "visualize_dag", {"project_path": project_path}
        )
        assert "ProtocolComponent" in visualization
        triage = json.loads(
            await call_success(
                "triage_reconciliation_drift", {"project_path": project_path}
            )
        )
        assert triage["schema_version"]

        await call_success(
            "promote_spec",
            {"feature_name": "promote-me.md", "project_path": project_path},
        )
        promoted = tmp_path / ".aio-agentic-sdlc" / "specs" / "promote-me.md"
        assert promoted.read_text(encoding="utf-8") == "# Accepted micro-spec\n"
        assert not change.exists()

        traceability = await call_success(
            "validate_traceability", {"project_path": project_path}
        )
        assert traceability.startswith("Traceability Drift Detected:")

        await call_success(
            "remove_task", {"name": "Protocol task", "project_path": project_path}
        )
        backlog = json.loads((tmp_path / BACKLOG_FILE).read_text(encoding="utf-8"))
        assert "Protocol task" not in backlog["nodes"]

    assert set(results) == EXPECTED_TOOLS
    assert Path.cwd() == starting_cwd
