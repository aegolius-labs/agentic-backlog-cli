import json
import os
import stat
import tempfile
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from filelock import FileLock
from mcp import MCPError
from mcp.server import MCPServer
from mcp.types import CallToolResult
from pydantic import Field, ValidationError

from .core import (
    VALID_STATUSES,
    BacklogOperationError,
    add_blocker,
    add_item,
    get_next_item,
    load_backlog,
    prioritize_items,
    remove_item,
    set_status,
    update_item,
)
from .dag_manager import DAGManager, DAGNotFoundError, DAGValidationError
from .dag_models import Node, NodeType
from .dag_store import GuardedPathError, guarded_directory_path, guarded_file_path
from .dag_visualization import (
    DAGVisualizationEngine,
    DAGVisualizationError,
    render_dag,
)
from .drift_triage import DriftTriageEngine, DriftTriageError, TriageDecisionSet
from .intent_ir import IntentIR
from .intent_store import (
    IntentStoreError,
    create_intent_node_file,
    update_intent_file,
)
from .mapping import MappingApproval, MappingEngine, MappingError
from .reconciliation import ReconciliationEngine, ReconciliationError
from .state import BacklogStateError
from .templating_engine import (
    TemplateNotFoundError,
    TemplateValidationError,
)
from .templating_engine import (
    generate_document as generate_document_from_template,
)
from .workspace import (
    AUDIT_FILE,
    BACKLOG_FILE,
    CHANGES_DIR,
    CONFIG_FILE,
    INTENTION_DAG_FILE,
    MAPPING_LOCK_FILE,
    REALITY_DAG_FILE,
    SPECS_DIR,
    STATE_LOCK_FILE,
    WORKSPACE_DIR,
    WORKSPACE_MIGRATION_LOCK_FILE,
    WorkspaceMigrationError,
)

_PROTECTED_STATE_PATHS = (
    INTENTION_DAG_FILE,
    REALITY_DAG_FILE,
    BACKLOG_FILE,
    CONFIG_FILE,
    AUDIT_FILE,
    STATE_LOCK_FILE,
    MAPPING_LOCK_FILE,
    WORKSPACE_MIGRATION_LOCK_FILE,
    f"{WORKSPACE_DIR}/.intention-dag.yaml.lock",
    f"{WORKSPACE_DIR}/.reality-dag.yaml.lock",
    f"{WORKSPACE_DIR}/.spec-promotion.lock",
    f"{WORKSPACE_DIR}/semantic-cache.db",
    f"{WORKSPACE_DIR}/semantic-cache.db-journal",
    f"{WORKSPACE_DIR}/semantic-cache.db-shm",
    f"{WORKSPACE_DIR}/semantic-cache.db-wal",
    f"{WORKSPACE_DIR}/semantic-cache.lock",
)
_PROTECTED_SOURCE_DIRECTORIES = (".agents", ".git", "src")


class PromotionError(ValueError):
    """Raised when a guarded spec-promotion transition loses identity."""


@dataclass
class _ToolCallMarker:
    expected_error: bool = False


_TOOL_CALL_MARKER: ContextVar[_ToolCallMarker | None] = ContextVar(
    "aio_sdlc_tool_call_marker",
    default=None,
)


def _expected_error(message: str) -> str:
    """Mark one explicit domain failure while preserving direct Python strings."""

    marker = _TOOL_CALL_MARKER.get()
    if marker is not None:
        marker.expected_error = True
    return message


def _path_identity(path: str | Path) -> str:
    """Return a case-normalized, symlink-resolved absolute path identity."""

    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path))))


def _same_path(first: str | Path, second: str | Path) -> bool:
    if _path_identity(first) == _path_identity(second):
        return True
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def _is_within(path: str | Path, directory: str | Path) -> bool:
    candidate = _path_identity(path)
    parent = _path_identity(directory)
    try:
        return os.path.commonpath([candidate, parent]) == parent
    except ValueError:
        return False


def _protected_output_reason(
    project_root: Path,
    output_path: Path,
    *,
    allow_reality_dag: bool = False,
) -> str | None:
    for relative in _PROTECTED_STATE_PATHS:
        protected = project_root / relative
        if _same_path(output_path, protected):
            if (
                allow_reality_dag
                and relative == REALITY_DAG_FILE
                and _path_identity(output_path) == _path_identity(protected)
            ):
                return None
            return "output resolves to protected project state"
    for relative in _PROTECTED_SOURCE_DIRECTORIES:
        if _is_within(output_path, project_root / relative):
            return f"output resolves inside protected source directory '{relative}'"
    return None


def _stat_identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _path_matches_regular_identity(path: Path, identity: tuple[int, int]) -> bool:
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(current.st_mode) and _stat_identity(current) == identity


def _open_verified_regular_leaf(path: Path) -> tuple[int, os.stat_result]:
    """Open one regular leaf and bind its descriptor to the observed path identity."""

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        leaf = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(opened.st_mode) or _stat_identity(opened) != _stat_identity(
            leaf
        ):
            raise PromotionError("spec destination changed during promotion")
        return descriptor, opened
    except Exception:
        os.close(descriptor)
        raise


def _remove_leaf_without_following(path: Path) -> None:
    if not os.path.lexists(path):
        return
    current = os.stat(path, follow_symlinks=False)
    if stat.S_ISREG(current.st_mode):
        os.chmod(path, stat.S_IMODE(current.st_mode) | stat.S_IWUSR)
    os.unlink(path)


def _restore_regular_file_from_fd(
    descriptor: int,
    destination: Path,
    mode: int,
) -> None:
    if os.path.lexists(destination):
        raise PromotionError("spec source path changed during rollback")
    temporary_descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".rollback",
    )
    temporary = Path(temporary_name)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        with os.fdopen(temporary_descriptor, "wb") as handle:
            while chunk := os.read(descriptor, 1024 * 1024):
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_regular_file_to_atomic_temp(source: Path, destination_dir: Path) -> Path:
    """Copy one verified source handle without following a swapped leaf."""

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    source_fd = os.open(source, flags)
    temp_path: Path | None = None
    try:
        opened = os.fstat(source_fd)
        leaf = os.stat(source, follow_symlinks=False)
        if not stat.S_ISREG(opened.st_mode) or _stat_identity(opened) != _stat_identity(
            leaf
        ):
            raise PromotionError("spec source changed during promotion")

        temp_fd, temp_name = tempfile.mkstemp(
            dir=destination_dir,
            prefix=f".{source.name}.",
            suffix=".tmp",
        )
        temp_path = Path(temp_name)
        with (
            os.fdopen(source_fd, "rb", closefd=False) as source_file,
            os.fdopen(temp_fd, "wb") as destination_file,
        ):
            while chunk := source_file.read(1024 * 1024):
                destination_file.write(chunk)
            destination_file.flush()
            os.fsync(destination_file.fileno())
        os.chmod(temp_path, stat.S_IMODE(opened.st_mode))
        return temp_path
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    finally:
        os.close(source_fd)


# aio-sdlc-mapping-approval: {"approved_at":"2026-08-21T23:03:05.512658-04:00","approved_by":"Felix","candidate_reality_id":"55bef33d-15b7-588b-8712-a2ed3502be62","evidence_digest":"e8f0cc340f146fc08809192ed143f0c36b0dc10c345ef05a382e5382ce295094","intent_id":"86367041-79ce-5415-b107-ef60cf721bf3","rationale":"Felix approved _SanitizingMCPServer as the source identity anchor for MCP SDK v2 Integration because it is the instantiated MCPServer subclass owning the public server adapter and sanitized protocol error boundary; behavioral acceptance remains governed separately by QA evidence.","schema_version":1,"source_path":"src/aio_agentic_sdlc/mcp_server.py","source_sha256":"992b2d5362ecf7d2b1f6a8b49eed1b08c1b2b1d1b0e560c4d3bd5bf690e53021","symbol_kind":"class","symbol_name":"_SanitizingMCPServer"}
# aio-sdlc-node: 86367041-79ce-5415-b107-ef60cf721bf3
class _SanitizingMCPServer(MCPServer):
    """Keep unexpected tool failures useful without exposing internal details."""

    async def call_tool(self, name, arguments, context=None):
        marker = _ToolCallMarker()
        token = _TOOL_CALL_MARKER.set(marker)
        try:
            result = await super().call_tool(name, arguments, context)
        except MCPError:
            raise
        except Exception:
            raise RuntimeError(f"Tool '{name}' failed.") from None
        finally:
            _TOOL_CALL_MARKER.reset(token)
        if (
            isinstance(result, CallToolResult)
            and marker.expected_error
            and not result.is_error
        ):
            return result.model_copy(update={"is_error": True})
        return result


# Create the MCP server instance
mcp = _SanitizingMCPServer("Agentic Backlog")


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
    project_path: str = Field(
        ".", description="Absolute path to the project directory"
    ),
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
        return _expected_error(f"Error: Status must be one of {VALID_STATUSES}")
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
    except (BacklogOperationError, BacklogStateError, WorkspaceMigrationError) as e:
        return _expected_error(f"Error: {str(e)}")


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
        return _expected_error(f"Error: Status must be one of {VALID_STATUSES}")
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
    except (BacklogOperationError, BacklogStateError, WorkspaceMigrationError) as e:
        return _expected_error(f"Error: {str(e)}")


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
        return _expected_error(f"Error: Status must be one of {VALID_STATUSES}")
    try:
        set_status(name, new_status, project_path)
        return f"Task '{name}' status set to '{new_status}'."
    except (BacklogOperationError, BacklogStateError, WorkspaceMigrationError) as e:
        return _expected_error(f"Error: {str(e)}")


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
    except (BacklogOperationError, BacklogStateError, WorkspaceMigrationError) as e:
        return _expected_error(f"Error: {str(e)}")


@mcp.tool()
def prioritize_backlog(
    project_path: str = Field(
        ".", description="Absolute path to the project directory"
    ),
) -> str:
    """Force an immediate topological sort and priority re-calculation of the backlog."""
    try:
        if prioritize_items(project_path):
            return "Backlog successfully prioritized."
        return "Backlog is empty."
    except (BacklogOperationError, BacklogStateError, WorkspaceMigrationError) as e:
        return _expected_error(f"Error: {str(e)}")


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
    except (BacklogOperationError, BacklogStateError, WorkspaceMigrationError) as e:
        return _expected_error(f"Error: {str(e)}")


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

        project_root = guarded_directory_path(project_path)
        abs_target = Path(
            os.path.abspath(
                target_dir
                if os.path.isabs(target_dir)
                else os.path.join(project_root, target_dir)
            )
        )

        if not _is_within(abs_target, project_root):
            return _expected_error(
                "Error generating document: target_dir resolves outside of the project root."
            )

        output_path = Path(os.path.abspath(os.path.join(abs_target, output_filename)))

        if not _is_within(output_path, abs_target):
            return _expected_error(
                "Error generating document: output_filename resolves outside of target_dir."
            )

        protected_reason = _protected_output_reason(project_root, output_path)
        if protected_reason:
            return _expected_error(f"Error generating document: {protected_reason}.")
        output_path = guarded_file_path(output_path, create_parent=True)

        generate_document_from_template(
            template_name,
            data,
            output_path,
        )
        return f"Document successfully generated at {output_path}."
    except (
        json.JSONDecodeError,
        GuardedPathError,
        TemplateNotFoundError,
        TemplateValidationError,
        WorkspaceMigrationError,
    ) as e:
        return _expected_error(f"Error generating document: {str(e)}")


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
        return _expected_error(
            "Error: Semantic search dependencies not installed. Ensure "
            "sentence-transformers and sqlite-vec are available."
        )
    except WorkspaceMigrationError as e:
        return _expected_error(f"Error checking for duplicates: {str(e)}")


@mcp.tool()
def validate_traceability(
    project_path: str = Field(
        ".", description="Absolute path to the project directory"
    ),
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
    except (DAGNotFoundError, DAGValidationError, ValidationError) as e:
        return _expected_error(f"Error validating traceability: {str(e)}")


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
    except (
        DAGValidationError,
        DAGNotFoundError,
        ReconciliationError,
        ValidationError,
    ) as e:
        return _expected_error(f"Error reconciling DAGs: {str(e)}")


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
    except (
        DAGValidationError,
        DAGVisualizationError,
        DAGNotFoundError,
        ReconciliationError,
        ValidationError,
    ) as e:
        return _expected_error(f"Error visualizing DAGs: {str(e)}")


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
    except (
        DAGValidationError,
        DriftTriageError,
        DAGNotFoundError,
        ReconciliationError,
        ValidationError,
    ) as e:
        return _expected_error(f"Error triaging reconciliation drift: {str(e)}")


@mcp.tool()
def review_mapping(
    intent_id: Annotated[str, Field(description="Canonical Intention node GUID")],
    candidate_reality_id: Annotated[
        str,
        Field(
            description=(
                "Optional explicit current observed Reality GUID; omit for automatic "
                "name matching"
            )
        ),
    ] = None,
    project_path: Annotated[
        str, Field(description="Absolute path to the project directory")
    ] = ".",
) -> str:
    """Return a human-first decision brief plus fresh source-bound audit evidence."""

    try:
        intention_path = os.path.join(os.path.abspath(project_path), INTENTION_DAG_FILE)
        report = MappingEngine(project_path, intention_path).review(
            intent_id,
            candidate_reality_id=candidate_reality_id,
        )
        return json.dumps(report, indent=2)
    except (
        DAGValidationError,
        DAGNotFoundError,
        GuardedPathError,
        MappingError,
        ValidationError,
        WorkspaceMigrationError,
    ) as e:
        return _expected_error(f"Error reviewing mapping: {str(e)}")
    except FileNotFoundError:
        return _expected_error(
            "Error reviewing mapping: required source was not found."
        )


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
    selection_mode: Annotated[
        str,
        Field(
            description=(
                "Selection mode from the exact review: automatic_name_match or "
                "explicit_observed_guid"
            )
        ),
    ] = "automatic_name_match",
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
            selection_mode=selection_mode,
        )
        return json.dumps(result, indent=2)
    except (
        DAGValidationError,
        DAGNotFoundError,
        GuardedPathError,
        MappingError,
        ValidationError,
        WorkspaceMigrationError,
    ) as e:
        return _expected_error(f"Error approving mapping: {str(e)}")
    except FileNotFoundError:
        return _expected_error(
            "Error approving mapping: required source was not found."
        )


@mcp.tool()
def review_mapping_receipt(
    intent_id: Annotated[str, Field(description="Confirmed Intention node GUID")],
    project_path: Annotated[
        str, Field(description="Absolute path to the project directory")
    ] = ".",
) -> str:
    """Review fresh maintenance evidence for one confirmed source receipt."""

    try:
        intention_path = os.path.join(os.path.abspath(project_path), INTENTION_DAG_FILE)
        report = MappingEngine(project_path, intention_path).review_receipt_refresh(
            intent_id
        )
        return json.dumps(report, indent=2)
    except (
        DAGValidationError,
        DAGNotFoundError,
        GuardedPathError,
        MappingError,
        ValidationError,
        WorkspaceMigrationError,
    ) as error:
        return _expected_error(f"Error reviewing mapping receipt: {str(error)}")
    except FileNotFoundError:
        return _expected_error(
            "Error reviewing mapping receipt: required source was not found."
        )


@mcp.tool()
def refresh_mapping_receipt(
    intent_id: Annotated[str, Field(description="Confirmed Intention node GUID")],
    evidence_digest: Annotated[
        str, Field(description="Evidence digest from the exact receipt review")
    ],
    approved_by: Annotated[str, Field(description="Identity of the approver")],
    approved_at: Annotated[
        str, Field(description="Timezone-aware ISO-8601 approval timestamp")
    ],
    rationale: Annotated[str, Field(description="Reason for refreshing this receipt")],
    project_path: Annotated[
        str, Field(description="Absolute path to the project directory")
    ] = ".",
) -> str:
    """Atomically refresh one confirmed source receipt from exact approved evidence."""

    try:
        intention_path = os.path.join(os.path.abspath(project_path), INTENTION_DAG_FILE)
        approval = MappingApproval.model_validate(
            {
                "approved_by": approved_by,
                "approved_at": approved_at,
                "rationale": rationale,
            }
        )
        result = MappingEngine(project_path, intention_path).refresh_receipt(
            intent_id,
            evidence_digest,
            approval,
        )
        return json.dumps(result, indent=2)
    except (
        DAGValidationError,
        DAGNotFoundError,
        GuardedPathError,
        MappingError,
        ValidationError,
        WorkspaceMigrationError,
    ) as error:
        return _expected_error(f"Error refreshing mapping receipt: {str(error)}")
    except FileNotFoundError:
        return _expected_error(
            "Error refreshing mapping receipt: required source was not found."
        )


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
    except (
        DAGValidationError,
        DAGNotFoundError,
        GuardedPathError,
        IntentStoreError,
        ValidationError,
    ) as e:
        return _expected_error(f"Error setting Intent IR: {str(e)}")


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
    except (
        DAGValidationError,
        DAGNotFoundError,
        GuardedPathError,
        IntentStoreError,
        ValidationError,
    ) as e:
        return _expected_error(f"Error creating intent node: {str(e)}")


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
    except (DAGNotFoundError, DAGValidationError, ValidationError) as e:
        return _expected_error(f"Error validating Intent IR: {str(e)}")


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
    except (DAGNotFoundError, DAGValidationError, ValidationError) as e:
        return _expected_error(f"Error reviewing Intent IR: {str(e)}")


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
        if Path(feature_name).name != feature_name or feature_name in {"", ".", ".."}:
            return _expected_error(
                "Error promoting spec: feature_name must be one file name without traversal."
            )

        project_root = guarded_directory_path(project_path)
        changes_dir = guarded_directory_path(project_root / CHANGES_DIR)
        specs_dir = guarded_directory_path(project_root / SPECS_DIR)
        src_path = guarded_file_path(changes_dir / feature_name)
        dst_path = guarded_file_path(specs_dir / feature_name)
        lock_path = guarded_file_path(
            project_root / ".aio-agentic-sdlc" / ".spec-promotion.lock",
            create_parent=True,
        )

        with FileLock(lock_path, timeout=30, preserve_lock_file=True):
            src_path = guarded_file_path(src_path)
            dst_path = guarded_file_path(dst_path)
            if not src_path.exists():
                return _expected_error(
                    f"Error: Spec '{feature_name}' not found in {CHANGES_DIR}/."
                )
            if dst_path.exists():
                return _expected_error(
                    f"Error promoting spec: Spec '{feature_name}' already exists in {SPECS_DIR}/."
                )
            source_stat = os.stat(src_path, follow_symlinks=False)
            source_identity = _stat_identity(source_stat)
            source_mode = stat.S_IMODE(source_stat.st_mode)
            temp_path = _copy_regular_file_to_atomic_temp(src_path, specs_dir)
            destination_committed = False
            destination_fd: int | None = None
            destination_identity: tuple[int, int] | None = None
            source_mode_changed = False
            source_removal_started = False
            source_removed = False
            try:
                src_path = guarded_file_path(src_path)
                if not _path_matches_regular_identity(src_path, source_identity):
                    raise PromotionError("spec source changed during promotion")
                dst_path = guarded_file_path(dst_path)
                if dst_path.exists():
                    raise PromotionError("spec destination changed during promotion")
                os.replace(temp_path, dst_path)
                destination_committed = True

                destination_fd, committed_stat = _open_verified_regular_leaf(dst_path)
                destination_identity = _stat_identity(committed_stat)
                dst_path = guarded_file_path(dst_path)
                if not _path_matches_regular_identity(dst_path, destination_identity):
                    raise PromotionError("spec destination changed during promotion")

                src_path = guarded_file_path(src_path)
                if not _path_matches_regular_identity(src_path, source_identity):
                    raise PromotionError("spec source changed during promotion")
                dst_path = guarded_file_path(dst_path)
                if not _path_matches_regular_identity(dst_path, destination_identity):
                    raise PromotionError("spec destination changed during promotion")

                if source_mode & stat.S_IWUSR == 0:
                    os.chmod(src_path, source_mode | stat.S_IWUSR)
                    source_mode_changed = True
                    if not _path_matches_regular_identity(src_path, source_identity):
                        raise PromotionError("spec source changed during promotion")
                source_removal_started = True
                os.unlink(src_path)
                source_removed = True

                dst_path = guarded_file_path(dst_path)
                if not _path_matches_regular_identity(dst_path, destination_identity):
                    raise PromotionError("spec destination changed during promotion")
            except Exception as transition_error:
                temp_path.unlink(missing_ok=True)
                if source_removal_started and not os.path.lexists(src_path):
                    source_removed = True
                rollback_error: Exception | None = None
                if source_removed and destination_fd is not None:
                    try:
                        _restore_regular_file_from_fd(
                            destination_fd,
                            src_path,
                            source_mode,
                        )
                        source_removed = False
                    except Exception as error:
                        rollback_error = error
                elif source_mode_changed and _path_matches_regular_identity(
                    src_path, source_identity
                ):
                    try:
                        os.chmod(src_path, source_mode)
                    except OSError as error:
                        rollback_error = error

                if destination_fd is not None:
                    os.close(destination_fd)
                    destination_fd = None
                if destination_committed and os.path.lexists(dst_path):
                    try:
                        _remove_leaf_without_following(dst_path)
                        destination_committed = False
                    except OSError as error:
                        rollback_error = rollback_error or error
                if rollback_error is not None:
                    raise PromotionError(
                        "spec promotion rollback failed closed"
                    ) from rollback_error
                raise transition_error
            finally:
                if destination_fd is not None:
                    os.close(destination_fd)

        if not dst_path.exists():
            return _expected_error(
                f"Error: Spec '{feature_name}' not found in {CHANGES_DIR}/."
            )
        return f"Successfully promoted spec '{feature_name}' to {SPECS_DIR}/."
    except (
        GuardedPathError,
        PromotionError,
        WorkspaceMigrationError,
    ) as e:
        return _expected_error(f"Error promoting spec: {str(e)}")
    except FileNotFoundError:
        return _expected_error(
            "Error promoting spec: required project artifact was not found."
        )
    except OSError:
        return _expected_error("Error promoting spec: filesystem transition failed.")


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
        project_root = guarded_directory_path(project_path)
        requested_output = Path(output)
        output_path = (
            requested_output
            if requested_output.is_absolute()
            else project_root / requested_output
        )
        output_path = Path(os.path.abspath(output_path))
        if not _is_within(output_path, project_root):
            return _expected_error(
                "Error generating Reality DAG: output resolves outside of the project root."
            )
        protected_reason = _protected_output_reason(
            project_root,
            output_path,
            allow_reality_dag=True,
        )
        if protected_reason:
            return _expected_error(f"Error generating Reality DAG: {protected_reason}.")
        output_path = guarded_file_path(output_path, create_parent=True)

        result = subprocess.run(
            [
                "uv",
                "run",
                "dag-tool",
                "generate-reality",
                "--dir",
                project_path,
                "--output",
                str(output_path),
                "--system",
                system,
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return f"Reality DAG successfully generated at {output}.\n{result.stdout}"
        else:
            return _expected_error(
                f"Error generating Reality DAG (Exit Code {result.returncode}): "
                "diagnostic output was suppressed."
            )
    except (GuardedPathError, WorkspaceMigrationError) as e:
        return _expected_error(f"Error executing dag-tool: {str(e)}")
    except FileNotFoundError:
        return _expected_error(
            "Error executing dag-tool: executable or project artifact was not found."
        )
    except OSError:
        return _expected_error(
            "Error executing dag-tool: process or filesystem operation failed."
        )


def main():
    mcp.run()


if __name__ == "__main__":
    main()
