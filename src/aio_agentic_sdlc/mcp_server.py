import json
import os
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .core import (
    VALID_STATUSES,
    add_blocker,
    add_item,
    get_next_item,
    load_backlog,
    prioritize_items,
    remove_item,
    set_status,
    update_item,
)
from .dag_manager import DAGManager
from .dag_models import Node, NodeType
from .dag_visualization import DAGVisualizationEngine, render_dag
from .drift_triage import DriftTriageEngine, TriageDecisionSet
from .intent_ir import IntentIR
from .intent_store import create_intent_node_file, update_intent_file
from .mapping import MappingApproval, MappingEngine
from .reconciliation import ReconciliationEngine
from .templating_engine import generate_document as generate_document_from_template
from .workspace import (
    CHANGES_DIR,
    INTENTION_DAG_FILE,
    REALITY_DAG_FILE,
    SPECS_DIR,
)

# Create the MCP server instance
mcp = FastMCP("Agentic Backlog")


@mcp.resource("backlog://current")
def read_current_backlog() -> str:
    """Read the complete prioritized project backlog as JSON from the current working directory."""
    data = load_backlog()
    return json.dumps(data, indent=2)


@mcp.resource("backlog://hierarchy-rules")
def read_hierarchy_rules() -> str:
    """Read the validation mode and graph hierarchy rules."""
    from .config import load_config

    config = load_config(".")
    return json.dumps(
        {
            "hierarchy": config.get(
                "hierarchy", {"1": ["Epic"], "2": ["Feature"], "3": ["Task", "Bug"]}
            ),
            "validation_mode": config.get("core", {}).get("validation_mode", "flex"),
        },
        indent=2,
    )


@mcp.prompt("pick-next-task")
def pick_next_task_prompt() -> str:
    """Prompt the agent to pick the next workable task from the backlog."""
    return (
        "Please read the project backlog (you can use get_next_task or the backlog://current resource), "
        "identify the highest priority workable task, and execute it."
    )


@mcp.tool()
def get_next_task(
    project_path: str = Field(".", description="Absolute path to the project directory")
) -> str:
    """Find and return the highest-priority workable task from the backlog."""
    target_data, warning = get_next_item(project_path)
    if not target_data:
        return f"Warning: {warning}"
    return json.dumps({"target": target_data, "warning": warning}, indent=2)


@mcp.tool()
def add_task(
    name: str = Field(..., description="The name of the new task"),
    impact: int = Field(..., description="Impact score from 1-5"),
    effort: int = Field(..., description="Effort score from 1-5 (1=Easy, 5=Hard)"),
    category: str = Field(..., description="Category (e.g. Core, Feature, Bug)"),
    description: str = Field(..., description="Detailed task description"),
    requires: str = Field(
        "", description="Comma-separated list of required task names"
    ),
    status: str = Field("New", description="Initial status"),
    project_path: str = Field(
        ".", description="Absolute path to the project directory"
    ),
    item_type: str = Field(
        "Task", description="Type of the item based on hierarchy rules"
    ),
    parent_id: str = Field(None, description="Parent item ID if applicable"),
) -> str:
    """Add a new task to the project backlog."""
    if status not in VALID_STATUSES:
        return f"Error: Status must be one of {VALID_STATUSES}"
    try:
        warnings = add_item(
            name=name,
            impact=impact,
            effort=effort,
            category=category,
            description=description,
            requires=requires,
            ai_driven=True,
            status=status,
            project_path=project_path,
            item_type=item_type,
            parent_id=parent_id,
        )
        msg = f"Task '{name}' added successfully."
        if warnings:
            msg += "\nWarnings:\n" + "\n".join(warnings)
        return msg
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def update_task(
    name: str = Field(..., description="The name of the task to update"),
    impact: int = Field(None, description="Impact score from 1-5"),
    effort: int = Field(None, description="Effort score from 1-5 (1=Easy, 5=Hard)"),
    category: str = Field(None, description="Category (e.g. Core, Feature, Bug)"),
    description: str = Field(None, description="Detailed task description"),
    requires: str = Field(
        None, description="Comma-separated list of required task names"
    ),
    status: str = Field(None, description="Status"),
    project_path: str = Field(
        ".", description="Absolute path to the project directory"
    ),
    item_type: str = Field(
        None, description="Type of the item based on hierarchy rules"
    ),
    parent_id: str = Field(None, description="Parent item ID if applicable"),
) -> str:
    """Update an existing task in the project backlog."""
    if status is not None and status not in VALID_STATUSES:
        return f"Error: Status must be one of {VALID_STATUSES}"
    try:
        warnings = update_item(
            name=name,
            impact=impact,
            effort=effort,
            category=category,
            description=description,
            requires=requires,
            ai_driven=None,
            status=status,
            blockers=None,
            project_path=project_path,
            item_type=item_type,
            parent_id=parent_id,
        )
        msg = f"Task '{name}' updated successfully."
        if warnings:
            msg += "\nWarnings:\n" + "\n".join(warnings)
        return msg
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def update_task_status(
    name: str = Field(..., description="Task name"),
    new_status: str = Field(
        ..., description="New status ('New', 'In Progress', 'Completed', 'Blocked')"
    ),
    project_path: str = Field(
        ".", description="Absolute path to the project directory"
    ),
) -> str:
    """Quickly update the status of an existing task."""
    if new_status not in VALID_STATUSES:
        return f"Error: Status must be one of {VALID_STATUSES}"
    try:
        set_status(name, new_status, project_path)
        return f"Task '{name}' status set to '{new_status}'."
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def remove_task(
    name: str = Field(..., description="Task name"),
    project_path: str = Field(
        ".", description="Absolute path to the project directory"
    ),
) -> str:
    """Remove a task entirely from the backlog."""
    try:
        remove_item(name, project_path)
        return f"Task '{name}' completely removed."
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def prioritize_backlog(
    project_path: str = Field(".", description="Absolute path to the project directory")
) -> str:
    """Force an immediate topological sort and priority re-calculation of the backlog."""
    try:
        if prioritize_items(project_path):
            return "Backlog successfully prioritized."
        return "Backlog is empty."
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def block_task(
    name: str = Field(..., description="Task name"),
    reason: str = Field(..., description="Why is it blocked?"),
    project_path: str = Field(
        ".", description="Absolute path to the project directory"
    ),
) -> str:
    """Add a blocker to a task, preventing it from being worked on."""
    try:
        add_blocker(name, reason, project_path)
        return f"Blocker added to '{name}'."
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def generate_document(
    template_name: str = Field(
        ..., description="Name of the template file (e.g. prd_template.md)"
    ),
    data_json: str = Field(
        ..., description="JSON string containing the data to populate the template"
    ),
    output_filename: str = Field(..., description="Name of the output file"),
    target_dir: Annotated[
        str, Field(description="Directory where the document will be saved")
    ] = CHANGES_DIR,
    project_path: Annotated[
        str, Field(description="Absolute path to the project directory")
    ] = ".",
) -> str:
    """Generate a document from a template using the provided data."""
    try:
        data = json.loads(data_json)
        if not isinstance(project_path, str):
            project_path = "."

        project_root = os.path.abspath(project_path)
        abs_target = os.path.abspath(
            target_dir
            if os.path.isabs(target_dir)
            else os.path.join(project_root, target_dir)
        )

        if os.path.commonpath([project_root, abs_target]) != project_root:
            return "Error generating document: target_dir resolves outside of the project root."

        output_path = os.path.abspath(os.path.join(abs_target, output_filename))

        if os.path.commonpath([abs_target, output_path]) != abs_target:
            return "Error generating document: output_filename resolves outside of target_dir."

        # Security: Prevent overwriting internal/sensitive folders
        rel_output = os.path.relpath(output_path, project_root).replace("\\", "/")
        if (
            rel_output.startswith(".agents/")
            or rel_output.startswith("src/")
            or rel_output.startswith(".git/")
        ):
            return "Error generating document: Cannot generate documents inside protected directories (.agents, src, .git)."

        generate_document_from_template(
            template_name,
            data,
            output_path,
        )
        return f"Document successfully generated at {output_path}."
    except Exception as e:
        return f"Error generating document: {str(e)}"


@mcp.tool()
def check_duplicate_prd(
    proposed_content: str = Field(
        ..., description="The content of the proposed PRD to check for duplicates"
    ),
    project_path: str = Field(
        ".", description="Absolute path to the project directory"
    ),
    similarity_threshold: float = Field(
        0.2,
        description="Cosine distance threshold (lower = more strict similarity, 0.2 means 80% similar)",
    ),
) -> str:
    """Check if a proposed PRD is similar to canonical project specs."""
    try:
        from .semantic_dedup import find_duplicate_prds

        results = find_duplicate_prds(
            proposed_content, project_path, similarity_threshold
        )
        if not results:
            return "No duplicates found."

        output = "Potential duplicates found:\n"
        for res in results:
            output += (
                f"- {res['filepath']} (Similarity: {res['similarity_score']:.2f})\n"
            )
        return output
    except ImportError:
        return "Error: Semantic search dependencies not installed. Ensure sentence-transformers and sqlite-vec are available."
    except Exception as e:
        return f"Error checking for duplicates: {str(e)}"


@mcp.tool()
def validate_traceability(
    project_path: str = Field(".", description="Absolute path to the project directory")
) -> str:
    """Validate that canonical specs align with both DAGs via GUID frontmatter."""
    try:
        from .core import TraceabilityValidator

        intention_path = os.path.join(project_path, INTENTION_DAG_FILE)
        reality_path = os.path.join(project_path, REALITY_DAG_FILE)
        specs_dir = os.path.join(project_path, SPECS_DIR)
        code_dir = os.path.join(project_path, "src")
        validator = TraceabilityValidator(
            intention_path=intention_path,
            reality_path=reality_path,
            specs_dir=specs_dir,
            code_dir=code_dir,
        )
        errors = validator.validate()
        if not errors:
            return "Traceability validation passed. No drift detected."
        return "Traceability Drift Detected:\n" + "\n".join(errors)
    except Exception as e:
        return f"Error validating traceability: {str(e)}"


@mcp.tool()
def reconcile_dags(
    project_path: Annotated[
        str, Field(description="Absolute path to the project directory")
    ] = ".",
    max_items: Annotated[
        int,
        Field(
            ge=1,
            description="Maximum evidence records returned; totals remain complete",
        ),
    ] = 100,
    max_candidates: Annotated[
        int,
        Field(
            ge=1,
            description="Maximum candidate identities retained per evidence record",
        ),
    ] = 20,
) -> str:
    """Classify Intention/Reality identity evidence without mutating project state."""

    try:
        project_root = os.path.abspath(project_path)
        intention = DAGManager.load(os.path.join(project_root, INTENTION_DAG_FILE))
        reality = DAGManager.load(os.path.join(project_root, REALITY_DAG_FILE))
        report = ReconciliationEngine(intention, reality).analyze(
            max_items=max_items,
            max_candidates=max_candidates,
        )
        return json.dumps(report, indent=2)
    except Exception as e:
        return f"Error reconciling DAGs: {str(e)}"


@mcp.tool()
def visualize_dag(
    project_path: Annotated[
        str, Field(description="Absolute path to the project directory")
    ] = ".",
    view: Annotated[
        str,
        Field(description="DAG view: intention, reality, or comparison"),
    ] = "comparison",
    focus_node_id: Annotated[
        str,
        Field(description="Optional canonical node GUID for a focused neighborhood"),
    ] = "",
    depth: Annotated[
        int,
        Field(ge=0, description="Incoming and outgoing neighborhood depth"),
    ] = 1,
    max_items: Annotated[
        int,
        Field(ge=1, description="Maximum records; totals remain complete"),
    ] = 100,
    max_edges: Annotated[
        int,
        Field(
            ge=1,
            description="Maximum intended and observed relationships per collection",
        ),
    ] = 200,
    max_candidates: Annotated[
        int,
        Field(
            ge=1,
            description="Maximum candidates and nested source locations per record",
        ),
    ] = 20,
    output_format: Annotated[
        str,
        Field(description="Output format: human, mermaid, or json"),
    ] = "human",
) -> str:
    """Render canonical DAG evidence without mutating project state."""

    try:
        engine = DAGVisualizationEngine.from_project(project_path)
        report = engine.build_report(
            view=view,
            focus_node_id=focus_node_id or None,
            depth=depth,
            max_items=max_items,
            max_edges=max_edges,
            max_candidates=max_candidates,
        )
        return render_dag(report, output_format)
    except Exception as e:
        return f"Error visualizing DAGs: {str(e)}"


@mcp.tool()
def triage_reconciliation_drift(
    project_path: Annotated[
        str, Field(description="Absolute path to the project directory")
    ] = ".",
    decisions_json: Annotated[
        str,
        Field(
            description=(
                "Optional digest-bound TriageDecisionSet JSON; leave empty for "
                "deterministic approval and observation routing"
            )
        ),
    ] = "",
    max_items: Annotated[
        int,
        Field(
            ge=1,
            description="Maximum triage records returned; totals remain complete",
        ),
    ] = 100,
) -> str:
    """Classify safe reconciliation work before backlog execution."""

    try:
        project_root = os.path.abspath(project_path)
        intention = DAGManager.load(os.path.join(project_root, INTENTION_DAG_FILE))
        reality = DAGManager.load(os.path.join(project_root, REALITY_DAG_FILE))
        decisions = (
            TriageDecisionSet.model_validate_json(decisions_json)
            if decisions_json.strip()
            else None
        )
        report = DriftTriageEngine(intention, reality).analyze(
            decisions=decisions,
            max_items=max_items,
        )
        return json.dumps(report, indent=2)
    except Exception as e:
        return f"Error triaging reconciliation drift: {str(e)}"


@mcp.tool()
def review_mapping(
    intent_id: Annotated[str, Field(description="Canonical Intention node GUID")],
    project_path: Annotated[
        str, Field(description="Absolute path to the project directory")
    ] = ".",
) -> str:
    """Return a human-first decision brief plus fresh source-bound audit evidence."""

    try:
        intention_path = os.path.join(os.path.abspath(project_path), INTENTION_DAG_FILE)
        report = MappingEngine(project_path, intention_path).review(intent_id)
        return json.dumps(report, indent=2)
    except Exception as e:
        return f"Error reviewing mapping: {str(e)}"


@mcp.tool()
def approve_mapping(
    intent_id: Annotated[str, Field(description="Canonical Intention node GUID")],
    candidate_reality_id: Annotated[
        str, Field(description="Reality candidate GUID from the exact mapping review")
    ],
    evidence_digest: Annotated[
        str, Field(description="Evidence digest from the exact mapping review")
    ],
    approved_by: Annotated[str, Field(description="Identity of the approver")],
    approved_at: Annotated[
        str, Field(description="Timezone-aware ISO-8601 approval timestamp")
    ],
    rationale: Annotated[str, Field(description="Reason for approving this mapping")],
    project_path: Annotated[
        str, Field(description="Absolute path to the project directory")
    ] = ".",
) -> str:
    """Approve one fresh candidate and atomically persist verified source evidence."""

    try:
        intention_path = os.path.join(os.path.abspath(project_path), INTENTION_DAG_FILE)
        approval = MappingApproval.model_validate(
            {
                "approved_by": approved_by,
                "approved_at": approved_at,
                "rationale": rationale,
            }
        )
        result = MappingEngine(project_path, intention_path).approve(
            intent_id,
            candidate_reality_id,
            evidence_digest,
            approval,
        )
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error approving mapping: {str(e)}"


@mcp.tool()
def set_intent(
    node_id: str = Field(..., description="Canonical Intention DAG node GUID"),
    payload_json: str = Field(
        ..., description="Complete JSON-encoded Intent IR v1 payload"
    ),
    expected_revision: int = Field(
        ..., ge=0, description="Current revision, or zero for creation"
    ),
    project_path: str = Field(
        ".", description="Absolute path to the project directory"
    ),
) -> str:
    """Create or revise one Intent IR payload with optimistic revision protection."""
    try:
        intention_path = os.path.join(os.path.abspath(project_path), INTENTION_DAG_FILE)
        intent = IntentIR.model_validate(json.loads(payload_json))
        revision = update_intent_file(
            intention_path,
            node_id,
            intent,
            expected_revision=expected_revision,
        )
        return f"Intent IR for node '{node_id}' saved at revision {revision}."
    except Exception as e:
        return f"Error setting Intent IR: {str(e)}"


@mcp.tool()
def create_intent_node(
    node_id: str = Field(..., description="Canonical Intention DAG node GUID"),
    node_type: str = Field(..., description="Canonical DAG node type"),
    name: str = Field(..., description="Human-readable node name"),
    payload_json: str = Field(
        ..., description="Initial JSON-encoded Intent IR v1 payload"
    ),
    domain: str = Field(None, description="Optional architectural domain"),
    description: str = Field(None, description="Optional node description"),
    project_path: str = Field(
        ".", description="Absolute path to the project directory"
    ),
) -> str:
    """Atomically create a canonical node with its initial Intent IR payload."""
    try:
        intention_path = os.path.join(os.path.abspath(project_path), INTENTION_DAG_FILE)
        node = Node(
            id=node_id,
            type=NodeType(node_type),
            name=name,
            domain=domain,
            description=description,
            intent=IntentIR.model_validate(json.loads(payload_json)),
        )
        revision = create_intent_node_file(intention_path, node)
        return f"Node '{node_id}' created with Intent IR revision {revision}."
    except Exception as e:
        return f"Error creating intent node: {str(e)}"


@mcp.tool()
def validate_intent(
    project_path: str = Field(
        ".", description="Absolute path to the project directory"
    ),
    require_all: bool = Field(True, description="Require Intent IR on every node"),
) -> str:
    """Validate Intent IR payloads and coverage in the canonical Intention DAG."""
    try:
        intention_path = os.path.join(os.path.abspath(project_path), INTENTION_DAG_FILE)
        manager = DAGManager.load(intention_path)
        manager.validate_intent_ir(require_all=require_all)
        return "Intent IR validation passed."
    except Exception as e:
        return f"Error validating Intent IR: {str(e)}"


@mcp.tool()
def review_intent(
    project_path: str = Field(
        ".", description="Absolute path to the project directory"
    ),
    node_id: str = Field(None, description="Optional node GUID to review"),
) -> str:
    """Render a human-readable review of canonical Intent IR payloads."""
    try:
        intention_path = os.path.join(os.path.abspath(project_path), INTENTION_DAG_FILE)
        return DAGManager.load(intention_path).render_intent_summary(node_id=node_id)
    except Exception as e:
        return f"Error reviewing Intent IR: {str(e)}"


@mcp.tool()
def promote_spec(
    feature_name: str = Field(
        ..., description="The name of the feature spec file (e.g. feature-123.md)"
    ),
    project_path: str = Field(
        ".", description="Absolute path to the project directory"
    ),
) -> str:
    """Move a validated micro-spec from changes to canonical specs."""
    try:
        import shutil

        changes_dir = os.path.join(project_path, CHANGES_DIR)
        specs_dir = os.path.join(project_path, SPECS_DIR)
        os.makedirs(specs_dir, exist_ok=True)

        src_path = os.path.join(changes_dir, feature_name)
        dst_path = os.path.join(specs_dir, feature_name)

        if not os.path.exists(src_path):
            return f"Error: Spec '{feature_name}' not found in {CHANGES_DIR}/."

        shutil.move(src_path, dst_path)
        return f"Successfully promoted spec '{feature_name}' to {SPECS_DIR}/."
    except Exception as e:
        return f"Error promoting spec: {str(e)}"


@mcp.tool()
def generate_reality(
    project_path: str = Field(
        ".", description="Absolute path to the project directory"
    ),
    output: str = Field(
        REALITY_DAG_FILE, description="Output filename for the Reality DAG"
    ),
    system: str = Field(
        "system_root", description="System root context for DAG generation"
    ),
) -> str:
    """Scan the codebase and update the Reality DAG via dag-tool."""
    import subprocess

    try:
        result = subprocess.run(
            [
                "uv",
                "run",
                "dag-tool",
                "generate-reality",
                "--dir",
                project_path,
                "--output",
                output,
                "--system",
                system,
            ],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return f"Reality DAG successfully generated at {output}.\n{result.stdout}"
        else:
            return f"Error generating Reality DAG (Exit Code {result.returncode}):\n{result.stderr}"
    except Exception as e:
        return f"Error executing dag-tool: {str(e)}"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
