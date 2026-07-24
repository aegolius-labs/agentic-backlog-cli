import asyncio

from google.antigravity import Agent, CapabilitiesConfig, LocalAgentConfig

from aio_agentic_sdlc import core
from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.diffing_engine import DiffingEngine


def ingest_diff():
    """
    Loads intention/reality DAGs via DAGManager, uses DiffingEngine to calculate the diff,
    and merges the resulting tasks and edges into the local backlog (backlog.json)
    using core.load_backlog and core.save_backlog, followed by core.prioritize_items.
    """
    intention_dag = DAGManager.load("intention-dag.yaml")
    reality_dag = DAGManager.load("reality-dag.yaml")

    diffing_engine = DiffingEngine(intention_dag, reality_dag)
    diff = diffing_engine.calculate_diff()
    tasks = diff.get("nodes", {})
    edges = diff.get("edges", [])

    backlog = core.load_backlog() or {}

    existing_items = backlog.get("nodes", {})
    for task_name, task in tasks.items() if isinstance(tasks, dict) else tasks:
        if isinstance(task, dict):
            task["id"] = task.get("id", task_name)
            task["name"] = task.get("name", task_name)
            existing_items[task["name"]] = task
        elif hasattr(task, "id"):
            existing_items[getattr(task, "name", task.id)] = task.__dict__

    backlog["nodes"] = existing_items

    existing_edges = {
        (e.get("source", e.get("from")), e.get("target", e.get("to"))): e
        for e in backlog.get("edges", [])
    }
    for edge in edges:
        if isinstance(edge, dict) and ("source" in edge or "from" in edge):
            src = edge.get("source", edge.get("from"))
            tgt = edge.get("target", edge.get("to"))
            existing_edges[(src, tgt)] = edge
        elif hasattr(edge, "source") and hasattr(edge, "target"):
            existing_edges[(edge.source, edge.target)] = edge.__dict__

    backlog["edges"] = list(existing_edges.values())

    core.save_backlog(backlog, operation="backlog.ingest-diff")
    core.prioritize_items()


async def execute_task_with_agent(task):
    """
    Instantiates the Agent using LocalAgentConfig. Configures system_instructions
    for the 'sdlc_orchestrator' role, applies CapabilitiesConfig, and streams
    the chat response for the task provided.
    """
    config = LocalAgentConfig(
        system_instructions="You are the sdlc_orchestrator. Please execute the following task.",
        capabilities=CapabilitiesConfig(),
    )

    task_desc = (
        task.get("description", "")
        if isinstance(task, dict)
        else getattr(task, "description", str(task))
    )
    prompt = f"Execute this task: {task_desc}"

    async with Agent(config) as agent:
        await agent.chat(prompt)


async def main_loop():
    """
    1. Invokes ingest_diff().
    2. Fetches the highest-priority unblocked task via core.get_next_item().
    3. Sets task status to 'In Progress' via core.set_status().
    4. Awaits execute_task_with_agent(task).
    5. Marks status 'Completed' (or 'Blocked' on failure).
    """
    ingest_diff()

    task = core.get_next_item()
    if not task:
        return

    task_id = task.get("id") if isinstance(task, dict) else getattr(task, "id", None)
    if not task_id:
        # Malformed task without an ID, we cannot process or mark it blocked
        return

    core.set_status(task_id, "In Progress")

    try:
        await execute_task_with_agent(task)
        core.set_status(task_id, "Completed")
    except Exception as e:
        core.set_status(task_id, "Blocked")
        raise e


if __name__ == "__main__":
    asyncio.run(main_loop())
