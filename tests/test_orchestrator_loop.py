from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aio_agentic_sdlc import orchestrator_loop


@pytest.fixture
def mock_dag_manager():
    with patch("aio_agentic_sdlc.orchestrator_loop.DAGManager") as MockDAGManager:
        yield MockDAGManager


@pytest.fixture
def mock_diffing_engine():
    with patch("aio_agentic_sdlc.orchestrator_loop.DiffingEngine") as MockDiffingEngine:
        yield MockDiffingEngine


@pytest.fixture
def mock_core():
    with patch("aio_agentic_sdlc.orchestrator_loop.core") as mock_core:
        yield mock_core


@pytest.fixture
def mock_agent():
    with patch(
        "aio_agentic_sdlc.orchestrator_loop.Agent", new_callable=MagicMock
    ) as mock_agent_class:
        mock_agent_instance = MagicMock()
        mock_agent_instance.chat = AsyncMock()
        mock_agent_instance.__aenter__ = AsyncMock(return_value=mock_agent_instance)
        mock_agent_instance.__aexit__ = AsyncMock(return_value=None)
        mock_agent_class.return_value = mock_agent_instance
        yield mock_agent_class


def test_ingest_diff(mock_dag_manager, mock_diffing_engine, mock_core):
    # Setup
    mock_dag_mgr_inst = mock_dag_manager.return_value
    mock_dag_mgr_inst.load_intention_dag.return_value = "intention_dag"
    mock_dag_mgr_inst.load_reality_dag.return_value = "reality_dag"

    mock_diff_eng_inst = mock_diffing_engine.return_value
    mock_diff_eng_inst.calculate_diff.return_value = {
        "nodes": {"t1": {"id": "t1", "desc": "task 1"}},
        "edges": [{"source": "t1", "target": "t2"}],
    }

    mock_core.load_backlog.return_value = {"items": [], "edges": []}

    # Execute
    orchestrator_loop.ingest_diff()

    # Assert
    mock_core.save_backlog.assert_called_once_with(
        {
            "items": [],
            "edges": [{"source": "t1", "target": "t2"}],
            "nodes": {"t1": {"id": "t1", "desc": "task 1", "name": "t1"}},
        },
        operation="backlog.ingest-diff",
    )
    mock_core.prioritize_items.assert_called_once()


def test_ingest_diff_empty(mock_dag_manager, mock_diffing_engine, mock_core):
    mock_diff_eng_inst = mock_diffing_engine.return_value
    mock_diff_eng_inst.calculate_diff.return_value = {"nodes": {}, "edges": []}
    mock_core.load_backlog.return_value = None  # test None backlog fallback

    orchestrator_loop.ingest_diff()

    mock_core.save_backlog.assert_called_once_with(
        {"nodes": {}, "edges": []}, operation="backlog.ingest-diff"
    )


def test_ingest_diff_overlapping_updates(
    mock_dag_manager, mock_diffing_engine, mock_core
):
    mock_diff_eng_inst = mock_diffing_engine.return_value
    mock_diff_eng_inst.calculate_diff.return_value = {
        "nodes": {
            "t1": {"id": "t1", "desc": "updated task 1"},
            "t3": {"id": "t3", "desc": "new task"},
        },
        "edges": [{"source": "t1", "target": "t2"}],
    }

    mock_core.load_backlog.return_value = {
        "nodes": {
            "t1": {"id": "t1", "desc": "old task 1"},
            "t2": {"id": "t2", "desc": "task 2"},
        },
        "edges": [{"source": "t1", "target": "t2"}],
    }

    orchestrator_loop.ingest_diff()

    args, _ = mock_core.save_backlog.call_args
    saved = args[0]

    # t1 should be updated, t2 preserved, t3 added
    assert saved["nodes"]["t1"]["desc"] == "updated task 1"
    assert saved["nodes"]["t2"]["desc"] == "task 2"
    assert saved["nodes"]["t3"]["desc"] == "new task"


def test_ingest_diff_malformed_mocks(mock_dag_manager, mock_diffing_engine, mock_core):
    # If calculate_diff returns strings instead of dicts or objects, the code should just ignore them.
    mock_diff_eng_inst = mock_diffing_engine.return_value
    mock_diff_eng_inst.calculate_diff.return_value = {
        "nodes": {"invalid": "invalid_task_string"},
        "edges": ["invalid_edge_string"],
    }
    mock_core.load_backlog.return_value = {"items": [], "edges": [], "nodes": {}}

    orchestrator_loop.ingest_diff()

    mock_core.save_backlog.assert_called_once_with(
        {"items": [], "edges": [], "nodes": {}}, operation="backlog.ingest-diff"
    )


@pytest.mark.asyncio
async def test_execute_task_with_agent(mock_agent):
    task = {"id": "t1", "description": "do something"}

    await orchestrator_loop.execute_task_with_agent(task)

    mock_agent.assert_called_once()

    agent_inst = mock_agent.return_value
    agent_inst.chat.assert_called_once()

    args, kwargs = agent_inst.chat.call_args
    prompt = args[0] if args else kwargs.get("prompt", "")
    assert "do something" in prompt or "do something" in str(kwargs)


@pytest.mark.asyncio
async def test_main_loop(mock_core, mock_agent):
    with patch("aio_agentic_sdlc.orchestrator_loop.ingest_diff") as mock_ingest:
        with patch(
            "aio_agentic_sdlc.orchestrator_loop.execute_task_with_agent",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_task = {"id": "t1"}
            mock_core.get_next_item.return_value = mock_task

            await orchestrator_loop.main_loop()

            mock_ingest.assert_called_once()
            mock_core.get_next_item.assert_called_once()
            mock_core.set_status.assert_any_call("t1", "In Progress")
            mock_exec.assert_called_once_with(mock_task)
            mock_core.set_status.assert_any_call("t1", "Completed")


@pytest.mark.asyncio
async def test_main_loop_failure(mock_core, mock_agent):
    with patch("aio_agentic_sdlc.orchestrator_loop.ingest_diff") as mock_ingest:
        with patch(
            "aio_agentic_sdlc.orchestrator_loop.execute_task_with_agent",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.side_effect = Exception("Agent failed")

            mock_task = {"id": "t1"}
            mock_core.get_next_item.return_value = mock_task

            with pytest.raises(Exception):
                await orchestrator_loop.main_loop()

            mock_ingest.assert_called_once()
            mock_core.set_status.assert_any_call("t1", "Blocked")


@pytest.mark.asyncio
async def test_main_loop_malformed_task(mock_core, mock_agent):
    with patch("aio_agentic_sdlc.orchestrator_loop.ingest_diff") as mock_ingest:
        # Task without id
        mock_core.get_next_item.return_value = {"desc": "no id"}

        await orchestrator_loop.main_loop()

        mock_ingest.assert_called_once()
        # set_status should not be called
        mock_core.set_status.assert_not_called()
