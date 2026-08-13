import json
import sys
from pathlib import Path

import click

from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Edge, EdgeType, Node, NodeType
from aio_agentic_sdlc.diffing_engine import DiffingEngine, DiffPolicy
from aio_agentic_sdlc.intent_ir import IntentIR
from aio_agentic_sdlc.intent_store import create_intent_node_file, update_intent_file
from aio_agentic_sdlc.mapping import MappingApproval, MappingEngine
from aio_agentic_sdlc.reality_dag_generator import RealityDAGGenerator
from aio_agentic_sdlc.reconciliation import (
    ReconciliationEngine,
    write_reconciliation_report,
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
def mapping_review(project_path, intent_id):
    """Render fresh source-bound evidence for one mapping decision."""

    try:
        engine = MappingEngine(project_path, Path(project_path) / "intention-dag.yaml")
        click.echo(json.dumps(engine.review(intent_id), indent=2))
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
    approved_by,
    approved_at,
    rationale,
):
    """Approve exactly one fresh candidate and persist verified source evidence."""

    try:
        engine = MappingEngine(project_path, Path(project_path) / "intention-dag.yaml")
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
        )
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        click.secho(f"Error approving mapping: {str(e)}", err=True, fg="red")
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
        generator = RealityDAGGenerator(root_dir=dir, system_name=system)
        reality_dag = generator.generate()
        reality_dag.save(output)
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
        manager = DAGManager.load(file)
        node_obj = Node(
            id=id,
            type=NodeType(type),
            name=name,
            domain=domain,
            description=description,
        )
        manager.add_node(node_obj)
        manager.save(file)
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
        manager = DAGManager.load(file)
        manager.update_node(id, name=name, domain=domain, description=description)
        manager.save(file)
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
        manager = DAGManager.load(file)
        manager.remove_node(id)
        manager.save(file)
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
        manager = DAGManager.load(file)
        edge_obj = Edge(
            source=source, target=target, type=EdgeType(type), description=description
        )
        manager.add_edge(edge_obj)
        manager.save(file)
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
        manager = DAGManager.load(file)
        manager.remove_edge(source, target, EdgeType(type))
        manager.save(file)
        click.echo(f"Edge {source} -> {target} ({type}) removed successfully.")
    except Exception as e:
        click.secho(f"Error removing edge: {str(e)}", err=True, fg="red")
        sys.exit(1)


if __name__ == "__main__":
    cli()
