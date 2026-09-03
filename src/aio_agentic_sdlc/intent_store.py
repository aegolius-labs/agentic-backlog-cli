"""Serialized, optimistic updates for Intent IR in canonical DAG files."""

from pathlib import Path

from .dag_models import Node
from .dag_store import mutate_dag_file
from .intent_ir import IntentIR


class IntentStoreError(ValueError):
    """Raised for an expected optimistic Intent IR mutation rejection."""


def create_intent_node_file(filepath: str | Path, node: Node) -> int:
    """Atomically create one canonical DAG node with validated Intent IR."""
    if node.intent is None:
        raise IntentStoreError("canonical intent node creation requires Intent IR")
    if (
        len(node.intent.revision_history) != 1
        or node.intent.revision_history[0].revision != 1
    ):
        raise IntentStoreError(
            "new canonical intent node must contain exactly revision 1"
        )

    def create(manager):
        manager.add_node(node)
        return node.intent.revision_history[-1].revision

    return mutate_dag_file(filepath, create)


def update_intent_file(
    filepath: str | Path,
    node_id: str,
    intent: IntentIR,
    *,
    expected_revision: int,
) -> int:
    """Create or revise one node's Intent IR without rewriting audit history."""
    if expected_revision < 0:
        raise IntentStoreError("expected_revision must be zero or greater")

    def update(manager):
        node = manager.get_node(node_id)
        current = node.intent
        current_revision = current.revision_history[-1].revision if current else 0
        if current_revision != expected_revision:
            raise IntentStoreError(
                f"stale Intent IR revision for node {node_id}: "
                f"expected {expected_revision}, found {current_revision}"
            )

        if current is None:
            if (
                len(intent.revision_history) != 1
                or intent.revision_history[0].revision != 1
            ):
                raise IntentStoreError("new Intent IR must contain exactly revision 1")
        else:
            existing_history = current.revision_history
            proposed_history = intent.revision_history
            if (
                len(proposed_history) != len(existing_history) + 1
                or proposed_history[:-1] != existing_history
            ):
                raise IntentStoreError(
                    "Intent IR revision must preserve existing revision history "
                    "and append one entry"
                )
            if proposed_history[-1].revision != current_revision + 1:
                raise IntentStoreError(
                    f"next Intent IR revision must be {current_revision + 1}"
                )

        manager.update_node(node_id, intent=intent)
        return intent.revision_history[-1].revision

    return mutate_dag_file(filepath, update)
