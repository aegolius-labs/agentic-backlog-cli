import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Edge, EdgeType, Node, NodeType
from aio_agentic_sdlc.dag_store import (
    dag_file_lock,
    guarded_dag_path,
    guarded_file_path,
    mutate_dag_file,
)
from aio_agentic_sdlc.dag_visualization import DAGVisualizationEngine, render_dag
from aio_agentic_sdlc.diffing_engine import DiffingEngine, DiffPolicy
from aio_agentic_sdlc.drift_triage import (
    DriftTriageEngine,
    TriageDecisionSet,
    render_drift_triage,
)
from aio_agentic_sdlc.intent_ir import IntentIR
from aio_agentic_sdlc.intent_migration import LegacyIntentMigrator
from aio_agentic_sdlc.intent_store import create_intent_node_file, update_intent_file
from aio_agentic_sdlc.mapping import (
    MappingApproval,
    MappingEngine,
    render_mapping_review,
    render_receipt_refresh_review,
)
from aio_agentic_sdlc.reality_dag_generator import RealityDAGGenerator
from aio_agentic_sdlc.reconciliation import (
    ReconciliationEngine,
    validate_reconciliation_report_output,
    write_reconciliation_report,
)
from aio_agentic_sdlc.workspace import (
    BACKLOG_FILE,
    INTENTION_DAG_FILE,
    REALITY_DAG_FILE,
)


@click.group()
def cli():
    """CLI tool for managing DAG state files safely."""
    pass


@cli.command()
@click.option(
    "--file",
    required=True,
    type=click.Path(exists=True),
    help="Path to the DAG yaml file.",
)
def validate(file):
    """Validates the structure and constraints of the DAG file."""
    try:
        manager = DAGManager.load(file)
        manager.validate()
        click.echo("DAG is valid.")
    except Exception as e:
        click.secho(f"Error validating DAG: {str(e)}", err=True, fg="red")
        sys.exit(1)


@cli.command("validate-intent")
@click.option(
    "--file",
    required=True,
    type=click.Path(exists=True),
    help="Path to the Intention DAG yaml file.",
)
@click.option(
    "--require-all/--allow-partial",
    default=True,
    help="Require every node to contain Intent IR or allow legacy nodes.",
)
def validate_intent(file, require_all):
    """Validate the Intent IR payloads and coverage of an Intention DAG."""
    try:
        manager = DAGManager.load(file)
        manager.validate_intent_ir(require_all=require_all)
        click.echo("Intent IR is valid.")
    except Exception as e:
        click.secho(f"Error validating Intent IR: {str(e)}", err=True, fg="red")
        sys.exit(1)


@cli.command("intent-summary")
@click.option(
    "--file",
    required=True,
    type=click.Path(exists=True),
    help="Path to the Intention DAG yaml file.",
)
@click.option("--node-id", help="Limit the review to one node ID.")
def intent_summary(file, node_id):
    """Render a human-readable Intent IR review without raw YAML."""
    try:
        manager = DAGManager.load(file)
        click.echo(manager.render_intent_summary(node_id=node_id))
    except Exception as e:
        click.secho(f"Error rendering Intent IR: {str(e)}", err=True, fg="red")
        sys.exit(1)


@cli.group("intent")
def intent():
    """Create or revise protected Intent IR payloads."""
    pass


@intent.command("create-node")
@click.option(
    "--file",
    required=True,
    type=click.Path(exists=True),
    help="Path to the Intention DAG yaml file.",
)
@click.option("--node-id", required=True, help="Canonical node GUID.")
@click.option(
    "--type", "node_type", required=True, type=click.Choice([t.value for t in NodeType])
)
@click.option("--name", required=True, help="Node name.")
@click.option("--domain", help="Node domain.")
@click.option("--description", help="Node description.")
@click.option(
    "--payload-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="JSON file containing the initial Intent IR v1 payload.",
)
def intent_create_node(
    file, node_id, node_type, name, domain, description, payload_file
):
    """Atomically create one canonical node with its initial Intent IR."""
    try:
        with open(payload_file, "r", encoding="utf-8") as payload:
            intent_ir = IntentIR.model_validate(json.load(payload))
        node = Node(
            id=node_id,
            type=NodeType(node_type),
            name=name,
            domain=domain,
            description=description,
            intent=intent_ir,
        )
        revision = create_intent_node_file(file, node)
        click.echo(f"Node '{node_id}' created with Intent IR revision {revision}.")
    except Exception as e:
        click.secho(f"Error creating intent node: {str(e)}", err=True, fg="red")
        sys.exit(1)


@intent.command("set")
@click.option(
    "--file",
    required=True,
    type=click.Path(exists=True),
    help="Path to the Intention DAG yaml file.",
)
@click.option(
    "--node-id", required=True, help="Node ID receiving the Intent IR payload."
)
@click.option(
    "--payload-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="JSON file containing one complete Intent IR payload.",
)
@click.option(
    "--expected-revision",
    required=True,
    type=click.IntRange(min=0),
    help="Current revision, or zero when creating the first Intent IR payload.",
)
def intent_set(file, node_id, payload_file, expected_revision):
    """Create or revise Intent IR using optimistic revision protection."""
    try:
        with open(payload_file, "r", encoding="utf-8") as payload:
            intent_ir = IntentIR.model_validate(json.load(payload))
        revision = update_intent_file(
            file,
            node_id,
            intent_ir,
            expected_revision=expected_revision,
        )
        click.echo(f"Intent IR for node '{node_id}' saved at revision {revision}.")
    except Exception as e:
        click.secho(f"Error setting Intent IR: {str(e)}", err=True, fg="red")
        sys.exit(1)


def _intent_migration_protected_paths(
    project_path: str | Path,
    *extra_paths: str | Path,
) -> tuple[Path, ...]:
    root = Path(project_path).resolve()
    return (
        root / INTENTION_DAG_FILE,
        root / REALITY_DAG_FILE,
        root / BACKLOG_FILE,
        *(Path(path).resolve() for path in extra_paths),
    )


def _write_intent_migration_artifact(
    payload: dict[str, Any],
    output: str | Path,
    project_path: str | Path,
    *,
    extra_protected_paths: tuple[str | Path, ...] = (),
) -> None:
    """Persist derived migration evidence without overwriting framework state."""

    write_reconciliation_report(
        payload,
        output,
        protected_paths=_intent_migration_protected_paths(
            project_path,
            *extra_protected_paths,
        ),
    )


@intent.command("inventory")
@click.option(
    "--project-path",
    required=True,
    type=click.Path(exists=True, file_okay=False),
    help="Absolute path to the project directory.",
)
@click.option(
    "--max-items",
    default=100,
    show_default=True,
    type=click.IntRange(min=0),
    help="Maximum legacy-node details to return while preserving complete totals.",
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False),
    help="Optional JSON report path; otherwise print the report.",
)
def intent_inventory(project_path, max_items, output):
    """Inventory legacy nodes with bounded detail and complete coverage totals."""

    try:
        report = LegacyIntentMigrator(project_path).inventory(max_items=max_items)
        if output:
            _write_intent_migration_artifact(report, output, project_path)
            click.echo(f"Legacy Intent IR inventory saved to {output}.")
        else:
            click.echo(json.dumps(report, indent=2))
    except Exception as e:
        click.secho(f"Error inventorying legacy intent: {str(e)}", err=True, fg="red")
        sys.exit(1)


@intent.command("plan-migration")
@click.option(
    "--project-path",
    required=True,
    type=click.Path(exists=True, file_okay=False),
    help="Absolute path to the project directory.",
)
@click.option(
    "--recorded-at",
    required=True,
    help="Timezone-aware ISO-8601 timestamp used for deterministic revision history.",
)
@click.option("--actor", required=True, help="Identity compiling the migration plan.")
@click.option(
    "--generator-version",
    required=True,
    help="Versioned compiler identity stored in each Intent IR revision.",
)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False),
    help="JSON migration-plan path.",
)
def intent_plan_migration(project_path, recorded_at, actor, generator_version, output):
    """Compile every legacy node into a deterministic review-required plan."""

    try:
        timestamp = datetime.fromisoformat(recorded_at)
        plan = LegacyIntentMigrator(project_path).plan(
            recorded_at=timestamp,
            actor=actor,
            generator_version=generator_version,
        )
        _write_intent_migration_artifact(plan, output, project_path)
        click.echo(
            f"Legacy Intent IR migration plan saved to {output} "
            f"for {plan['summary']['planned_migrations']} node(s)."
        )
    except Exception as e:
        click.secho(
            f"Error planning legacy intent migration: {str(e)}", err=True, fg="red"
        )
        sys.exit(1)


@intent.command("apply-migration")
@click.option(
    "--project-path",
    required=True,
    type=click.Path(exists=True, file_okay=False),
    help="Absolute path to the project directory.",
)
@click.option(
    "--plan-file",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Exact JSON migration plan produced by plan-migration.",
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False),
    help="Optional JSON result path; otherwise print the result.",
)
def intent_apply_migration(project_path, plan_file, output):
    """Atomically apply one complete, non-stale review-required migration plan."""

    try:
        if output:
            validate_reconciliation_report_output(
                output,
                protected_paths=_intent_migration_protected_paths(
                    project_path,
                    plan_file,
                ),
            )
        with open(plan_file, "r", encoding="utf-8") as handle:
            plan = json.load(handle)
        result = LegacyIntentMigrator(project_path).apply(plan)
        if output:
            try:
                _write_intent_migration_artifact(
                    result,
                    output,
                    project_path,
                    extra_protected_paths=(plan_file,),
                )
            except Exception as error:
                click.secho(
                    "Legacy Intent IR migration committed successfully, but result "
                    f"evidence could not be saved to {output}: {error}",
                    err=True,
                    fg="yellow",
                )
                click.echo(json.dumps(result, indent=2))
                return
            click.echo(f"Legacy Intent IR migration result saved to {output}.")
        else:
            click.echo(json.dumps(result, indent=2))
    except Exception as e:
        click.secho(
            f"Error applying legacy intent migration: {str(e)}", err=True, fg="red"
        )
        sys.exit(1)


@cli.group("mapping")
def mapping():
    """Review and explicitly approve source-bound identity mappings."""


@mapping.command("review")
@click.option(
    "--project-path",
    required=True,
    type=click.Path(exists=True, file_okay=False),
    help="Absolute path to the project directory.",
)
@click.option("--intent-id", required=True, help="Canonical Intention node GUID.")
@click.option(
    "--candidate-reality-id",
    help="Explicit current observed Reality GUID; omit for automatic name matching.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["human", "json"], case_sensitive=False),
    default="human",
    show_default=True,
    help="Render a decision brief for people or the complete machine report.",
)
def mapping_review(project_path, intent_id, candidate_reality_id, output_format):
    """Render fresh source-bound evidence for one mapping decision."""

    try:
        engine = MappingEngine(project_path, Path(project_path) / INTENTION_DAG_FILE)
        report = engine.review(
            intent_id,
            candidate_reality_id=candidate_reality_id,
        )
        if output_format == "json":
            click.echo(json.dumps(report, indent=2))
        else:
            click.echo(render_mapping_review(report))
    except Exception as e:
        click.secho(f"Error reviewing mapping: {str(e)}", err=True, fg="red")
        sys.exit(1)


@mapping.command("approve")
@click.option(
    "--project-path",
    required=True,
    type=click.Path(exists=True, file_okay=False),
    help="Absolute path to the project directory.",
)
@click.option("--intent-id", required=True, help="Canonical Intention node GUID.")
@click.option(
    "--candidate-reality-id",
    required=True,
    help="Reality candidate GUID from the exact mapping review.",
)
@click.option(
    "--evidence-digest",
    required=True,
    help="Evidence digest from the exact mapping review.",
)
@click.option(
    "--selection-mode",
    type=click.Choice(
        ["automatic_name_match", "explicit_observed_guid"],
        case_sensitive=True,
    ),
    default="automatic_name_match",
    show_default=True,
    help="Candidate selection mode used by the exact mapping review.",
)
@click.option("--approved-by", required=True, help="Identity of the approver.")
@click.option(
    "--approved-at",
    required=True,
    help="Timezone-aware ISO-8601 approval timestamp.",
)
@click.option("--rationale", required=True, help="Reason for approving this mapping.")
def mapping_approve(
    project_path,
    intent_id,
    candidate_reality_id,
    evidence_digest,
    selection_mode,
    approved_by,
    approved_at,
    rationale,
):
    """Approve exactly one fresh candidate and persist verified source evidence."""

    try:
        engine = MappingEngine(project_path, Path(project_path) / INTENTION_DAG_FILE)
        approval = MappingApproval.model_validate(
            {
                "approved_by": approved_by,
                "approved_at": approved_at,
                "rationale": rationale,
            }
        )
        result = engine.approve(
            intent_id,
            candidate_reality_id,
            evidence_digest,
            approval,
            selection_mode=selection_mode,
        )
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        click.secho(f"Error approving mapping: {str(e)}", err=True, fg="red")
        sys.exit(1)


@mapping.group("receipt")
def mapping_receipt():
    """Review and refresh confirmed source mapping receipts."""


@mapping_receipt.command("review")
@click.option(
    "--project-path",
    required=True,
    type=click.Path(exists=True, file_okay=False),
    help="Absolute path to the project directory.",
)
@click.option("--intent-id", required=True, help="Confirmed Intention node GUID.")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["human", "json"], case_sensitive=False),
    default="human",
    show_default=True,
    help="Render a decision brief for people or the complete machine report.",
)
def mapping_receipt_review(project_path, intent_id, output_format):
    """Render fresh maintenance evidence for one confirmed source receipt."""

    try:
        engine = MappingEngine(project_path, Path(project_path) / INTENTION_DAG_FILE)
        report = engine.review_receipt_refresh(intent_id)
        if output_format == "json":
            click.echo(json.dumps(report, indent=2))
        else:
            click.echo(render_receipt_refresh_review(report))
    except Exception as error:
        click.secho(
            f"Error reviewing mapping receipt: {str(error)}",
            err=True,
            fg="red",
        )
        sys.exit(1)


@mapping_receipt.command("refresh")
@click.option(
    "--project-path",
    required=True,
    type=click.Path(exists=True, file_okay=False),
    help="Absolute path to the project directory.",
)
@click.option("--intent-id", required=True, help="Confirmed Intention node GUID.")
@click.option(
    "--evidence-digest",
    required=True,
    help="Evidence digest from the exact receipt review.",
)
@click.option("--approved-by", required=True, help="Identity of the approver.")
@click.option(
    "--approved-at",
    required=True,
    help="Timezone-aware ISO-8601 approval timestamp.",
)
@click.option("--rationale", required=True, help="Reason for refreshing this receipt.")
def mapping_receipt_refresh(
    project_path,
    intent_id,
    evidence_digest,
    approved_by,
    approved_at,
    rationale,
):
    """Refresh exactly one confirmed receipt from approved fresh evidence."""

    try:
        engine = MappingEngine(project_path, Path(project_path) / INTENTION_DAG_FILE)
        approval = MappingApproval.model_validate(
            {
                "approved_by": approved_by,
                "approved_at": approved_at,
                "rationale": rationale,
            }
        )
        result = engine.refresh_receipt(intent_id, evidence_digest, approval)
        click.echo(json.dumps(result, indent=2))
    except Exception as error:
        click.secho(
            f"Error refreshing mapping receipt: {str(error)}",
            err=True,
            fg="red",
        )
        sys.exit(1)


@cli.command()
@click.option(
    "--intention",
    required=True,
    type=click.Path(exists=True),
    help="Path to the Intention DAG yaml file.",
)
@click.option(
    "--reality",
    required=True,
    type=click.Path(exists=True),
    help="Path to the Reality DAG yaml file.",
)
@click.option(
    "--mode",
    type=click.Choice(["safe", "legacy-structural"]),
    default="safe",
    show_default=True,
    help="Use evidence-gated planning or explicitly request legacy structural output.",
)
@click.option(
    "--max-tasks",
    type=click.IntRange(min=1),
    default=100,
    show_default=True,
    help="Maximum tasks returned by safe planning.",
)
@click.option(
    "--max-candidates",
    type=click.IntRange(min=1),
    default=20,
    show_default=True,
    help="Maximum candidate identities retained in each safe task.",
)
def diff(intention, reality, mode, max_tasks, max_candidates):
    """Calculates the diff between Intention DAG and Reality DAG."""
    try:
        intent_manager = DAGManager.load(intention)
        reality_manager = DAGManager.load(reality)
        policy = (
            DiffPolicy.safe(
                max_tasks=max_tasks,
                max_candidates=max_candidates,
            )
            if mode == "safe"
            else DiffPolicy.legacy_structural()
        )
        engine = DiffingEngine(intent_manager, reality_manager, policy=policy)
        diff_result = engine.calculate_diff()

        click.echo(json.dumps(diff_result, indent=2))
    except Exception as e:
        click.secho(f"Error computing diff: {str(e)}", err=True, fg="red")
        sys.exit(1)


@cli.command("reconcile")
@click.option(
    "--intention",
    required=True,
    type=click.Path(exists=True),
    help="Path to the canonical Intention DAG yaml file.",
)
@click.option(
    "--reality",
    required=True,
    type=click.Path(exists=True),
    help="Path to the generated Reality DAG yaml file.",
)
@click.option(
    "--max-items",
    type=click.IntRange(min=1),
    default=100,
    show_default=True,
    help="Maximum evidence records returned without hiding complete totals.",
)
@click.option(
    "--max-candidates",
    type=click.IntRange(min=1),
    default=20,
    show_default=True,
    help="Maximum candidate identities retained in each evidence record.",
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False),
    help="Atomically write the JSON report instead of printing it.",
)
def reconcile(intention, reality, max_items, max_candidates, output):
    """Render a bounded, read-only reconciliation evidence report."""

    try:
        intent_manager = DAGManager.load(intention)
        reality_manager = DAGManager.load(reality)
        report = ReconciliationEngine(intent_manager, reality_manager).analyze(
            max_items=max_items,
            max_candidates=max_candidates,
        )
        if output:
            write_reconciliation_report(
                report,
                output,
                protected_paths=(intention, reality),
            )
            click.echo(f"Reconciliation report saved to {output}.")
        else:
            click.echo(json.dumps(report, indent=2))
    except Exception as e:
        click.secho(f"Error reconciling DAGs: {str(e)}", err=True, fg="red")
        sys.exit(1)


@cli.command("visualize")
@click.option(
    "--project-path",
    required=True,
    type=click.Path(exists=True, file_okay=False),
    help="Path to the project containing the canonical framework workspace.",
)
@click.option(
    "--view",
    required=True,
    type=click.Choice(["intention", "reality", "comparison"], case_sensitive=False),
    help="DAG view to render.",
)
@click.option("--focus-node", "focus_node_id", help="Canonical node GUID to focus.")
@click.option(
    "--depth",
    type=click.IntRange(min=0),
    default=1,
    show_default=True,
    help="Incoming and outgoing neighborhood depth.",
)
@click.option(
    "--max-items",
    type=click.IntRange(min=1),
    default=100,
    show_default=True,
    help="Maximum records returned without hiding complete totals.",
)
@click.option(
    "--max-edges",
    type=click.IntRange(min=1),
    default=200,
    show_default=True,
    help="Maximum intended and observed relationships returned per collection.",
)
@click.option(
    "--max-candidates",
    type=click.IntRange(min=1),
    default=20,
    show_default=True,
    help="Maximum identity candidates and nested source locations per record.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["human", "mermaid", "json"], case_sensitive=False),
    default="human",
    show_default=True,
    help="Output rendering format.",
)
def visualize(
    project_path,
    view,
    focus_node_id,
    depth,
    max_items,
    max_edges,
    max_candidates,
    output_format,
):
    """Render canonical DAGs without mutating project or framework state."""

    try:
        engine = DAGVisualizationEngine.from_project(project_path)
        report = engine.build_report(
            view=view,
            focus_node_id=focus_node_id,
            depth=depth,
            max_items=max_items,
            max_edges=max_edges,
            max_candidates=max_candidates,
        )
        click.echo(render_dag(report, output_format))
    except Exception as e:
        click.secho(f"Error visualizing DAGs: {str(e)}", err=True, fg="red")
        sys.exit(1)


@cli.command("triage")
@click.option(
    "--intention",
    required=True,
    type=click.Path(exists=True),
    help="Path to the canonical Intention DAG yaml file.",
)
@click.option(
    "--reality",
    required=True,
    type=click.Path(exists=True),
    help="Path to the generated Reality DAG yaml file.",
)
@click.option(
    "--decisions",
    type=click.Path(exists=True, dir_okay=False),
    help="Optional digest-bound JSON triage decisions.",
)
@click.option(
    "--max-items",
    type=click.IntRange(min=1),
    default=100,
    show_default=True,
    help="Maximum triage records returned without hiding complete totals.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["human", "json"], case_sensitive=False),
    default="human",
    show_default=True,
    help="Render a human brief or the complete machine report.",
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False),
    help="Atomically write the JSON report instead of printing it.",
)
def triage(intention, reality, decisions, max_items, output_format, output):
    """Classify safe reconciliation work before backlog execution."""

    try:
        intent_manager = DAGManager.load(intention)
        reality_manager = DAGManager.load(reality)
        decision_set = None
        if decisions:
            decision_path = guarded_file_path(decisions)
            decision_set = TriageDecisionSet.model_validate_json(
                decision_path.read_text(encoding="utf-8")
            )
        report = DriftTriageEngine(intent_manager, reality_manager).analyze(
            decisions=decision_set,
            max_items=max_items,
        )
        if output:
            protected_paths = [intention, reality]
            if decisions:
                protected_paths.append(decisions)
            write_reconciliation_report(
                report,
                output,
                protected_paths=tuple(protected_paths),
            )
            click.echo(f"Drift triage report saved to {output}.")
        elif output_format.casefold() == "json":
            click.echo(json.dumps(report, indent=2))
        else:
            click.echo(render_drift_triage(report))
    except Exception as e:
        click.secho(
            f"Error triaging reconciliation drift: {str(e)}", err=True, fg="red"
        )
        sys.exit(1)


@cli.command("generate-reality")
@click.option(
    "--dir",
    required=True,
    type=click.Path(exists=True),
    help="Root directory to analyze.",
)
@click.option("--system", default="System", help="Name of the root system node.")
@click.option(
    "--output",
    required=True,
    type=click.Path(),
    help="Path to save the generated Reality DAG yaml file.",
)
def generate_reality(dir, system, output):
    """Generates a Reality DAG by statically analyzing source code in the given directory."""
    try:
        with dag_file_lock(output) as guarded_output:
            generator = RealityDAGGenerator(root_dir=dir, system_name=system)
            reality_dag = generator.generate()
            reality_dag.save(str(guarded_dag_path(guarded_output)))
        click.echo(f"Reality DAG generated and saved to {output}.")
    except Exception as e:
        click.secho(f"Error generating reality DAG: {str(e)}", err=True, fg="red")
        sys.exit(1)


@cli.group()
def node():
    """Node manipulation commands."""
    pass


@node.command("add")
@click.option(
    "--file",
    required=True,
    type=click.Path(exists=True),
    help="Path to the DAG yaml file.",
)
@click.option("--id", required=True, help="Node ID")
@click.option(
    "--type",
    required=True,
    type=click.Choice([t.value for t in NodeType]),
    help="Node Type",
)
@click.option("--name", required=True, help="Node Name")
@click.option("--domain", help="Node Domain")
@click.option("--description", help="Node Description")
def node_add(file, id, type, name, domain, description):
    """Add a new node."""
    try:
        node_obj = Node(
            id=id,
            type=NodeType(type),
            name=name,
            domain=domain,
            description=description,
        )
        mutate_dag_file(file, lambda manager: manager.add_node(node_obj))
        click.echo(f"Node '{id}' added successfully.")
    except Exception as e:
        click.secho(f"Error adding node: {str(e)}", err=True, fg="red")
        sys.exit(1)


@node.command("update")
@click.option(
    "--file",
    required=True,
    type=click.Path(exists=True),
    help="Path to the DAG yaml file.",
)
@click.option("--id", required=True, help="Node ID")
@click.option("--name", help="Node Name")
@click.option("--domain", help="Node Domain")
@click.option("--description", help="Node Description")
def node_update(file, id, name, domain, description):
    """Update an existing node."""
    try:
        mutate_dag_file(
            file,
            lambda manager: manager.update_node(
                id,
                name=name,
                domain=domain,
                description=description,
            ),
        )
        click.echo(f"Node '{id}' updated successfully.")
    except Exception as e:
        click.secho(f"Error updating node: {str(e)}", err=True, fg="red")
        sys.exit(1)


@node.command("remove")
@click.option(
    "--file",
    required=True,
    type=click.Path(exists=True),
    help="Path to the DAG yaml file.",
)
@click.option("--id", required=True, help="Node ID")
def node_remove(file, id):
    """Remove a node."""
    try:
        mutate_dag_file(file, lambda manager: manager.remove_node(id))
        click.echo(f"Node '{id}' removed successfully.")
    except Exception as e:
        click.secho(f"Error removing node: {str(e)}", err=True, fg="red")
        sys.exit(1)


@node.command("list")
@click.option(
    "--file",
    required=True,
    type=click.Path(exists=True),
    help="Path to the DAG yaml file.",
)
@click.option("--domain", help="Filter by Domain")
@click.option(
    "--type", type=click.Choice([t.value for t in NodeType]), help="Filter by Type"
)
@click.option(
    "--output",
    type=click.Choice(["json", "text"]),
    default="text",
    help="Output format",
)
def node_list(file, domain, type, output):
    """List nodes."""
    try:
        manager = DAGManager.load(file)
        node_type = NodeType(type) if type else None
        nodes = manager.find_nodes(domain=domain, type=node_type)

        if output == "json":
            click.echo(
                json.dumps(
                    [n.model_dump(mode="json", exclude_none=True) for n in nodes],
                    indent=2,
                )
            )
        else:
            for n in nodes:
                click.echo(f"{n.id} ({n.type.value}) - {n.name}")
    except Exception as e:
        click.secho(f"Error listing nodes: {str(e)}", err=True, fg="red")
        sys.exit(1)


@cli.group()
def edge():
    """Edge manipulation commands."""
    pass


@edge.command("add")
@click.option(
    "--file",
    required=True,
    type=click.Path(exists=True),
    help="Path to the DAG yaml file.",
)
@click.option("--source", required=True, help="Source Node ID")
@click.option("--target", required=True, help="Target Node ID")
@click.option(
    "--type",
    required=True,
    type=click.Choice([t.value for t in EdgeType]),
    help="Edge Type",
)
@click.option("--description", help="Edge Description")
def edge_add(file, source, target, type, description):
    """Add an edge."""
    try:
        edge_obj = Edge(
            source=source, target=target, type=EdgeType(type), description=description
        )
        mutate_dag_file(file, lambda manager: manager.add_edge(edge_obj))
        click.echo(f"Edge {source} -> {target} ({type}) added successfully.")
    except Exception as e:
        click.secho(f"Error adding edge: {str(e)}", err=True, fg="red")
        sys.exit(1)


@edge.command("remove")
@click.option(
    "--file",
    required=True,
    type=click.Path(exists=True),
    help="Path to the DAG yaml file.",
)
@click.option("--source", required=True, help="Source Node ID")
@click.option("--target", required=True, help="Target Node ID")
@click.option(
    "--type",
    required=True,
    type=click.Choice([t.value for t in EdgeType]),
    help="Edge Type",
)
def edge_remove(file, source, target, type):
    """Remove an edge."""
    try:
        mutate_dag_file(
            file,
            lambda manager: manager.remove_edge(source, target, EdgeType(type)),
        )
        click.echo(f"Edge {source} -> {target} ({type}) removed successfully.")
    except Exception as e:
        click.secho(f"Error removing edge: {str(e)}", err=True, fg="red")
        sys.exit(1)


if __name__ == "__main__":
    cli()
