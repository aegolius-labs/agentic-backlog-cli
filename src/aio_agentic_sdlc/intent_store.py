"""Serialized, optimistic updates for Intent IR in canonical DAG files."""

from pathlib import Path

from filelock import FileLock

from .dag_manager import DAGManager
from .dag_models import Node
from .intent_ir import IntentIR


def _lock_for(dag_path: Path) -> FileLock:
    dag_path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(dag_path.parent / f".{dag_path.name}.lock", timeout=10)


def create_intent_node_file(filepath: str | Path, node: Node) -> int:
    """Atomically create one canonical DAG node with validated Intent IR."""
    if node.intent is None:
        raise ValueError("canonical intent node creation requires Intent IR")
    if (
        len(node.intent.revision_history) != 1
        or node.intent.revision_history[0].revision != 1
    ):
        raise ValueError("new canonical intent node must contain exactly revision 1")

    dag_path = Path(filepath).resolve()
    with _lock_for(dag_path):
        manager = DAGManager.load(str(dag_path))
        manager.add_node(node)
        manager.save(str(dag_path))
        return node.intent.revision_history[-1].revision


def update_intent_file(
    filepath: str | Path,
    node_id: str,
    intent: IntentIR,
    *,
    expected_revision: int,
) -> int:
    """Create or revise one node's Intent IR without rewriting audit history."""
    if expected_revision < 0:
        raise ValueError("expected_revision must be zero or greater")

    dag_path = Path(filepath).resolve()
    with _lock_for(dag_path):
        manager = DAGManager.load(str(dag_path))
        node = manager.get_node(node_id)
        current = node.intent
        current_revision = current.revision_history[-1].revision if current else 0
        if current_revision != expected_revision:
            raise ValueError(
                f"stale Intent IR revision for node {node_id}: "
                f"expected {expected_revision}, found {current_revision}"
            )

        if current is None:
            if (
                len(intent.revision_history) != 1
                or intent.revision_history[0].revision != 1
            ):
                raise ValueError("new Intent IR must contain exactly revision 1")
        else:
            existing_history = current.revision_history
            proposed_history = intent.revision_history
            if (
                len(proposed_history) != len(existing_history) + 1
                or proposed_history[:-1] != existing_history
            ):
                raise ValueError(
                    "Intent IR revision must preserve existing revision history "
                    "and append one entry"
                )
            if proposed_history[-1].revision != current_revision + 1:
                raise ValueError(
                    f"next Intent IR revision must be {current_revision + 1}"
                )

        manager.update_node(node_id, intent=intent)
        manager.save(str(dag_path))
        return intent.revision_history[-1].revision
