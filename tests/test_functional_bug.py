from unittest.mock import AsyncMock, MagicMock, patch

from aio_agentic_sdlc.cli import plan_cmd
from aio_agentic_sdlc.workspace import INBOX_DIR


@patch("os.path.exists")
@patch("os.path.isdir")
@patch("glob.glob")
@patch("aio_agentic_sdlc.cli._run_architect_subagent", new_callable=AsyncMock)
@patch("aio_agentic_sdlc.dag_manager.DAGManager")
@patch("aio_agentic_sdlc.diffing_engine.DiffingEngine")
@patch("aio_agentic_sdlc.archiver.PRDArchiver")
@patch("builtins.open", new_callable=MagicMock)
def test_cli_unconditional_archival_edge_case(
    mock_open,
    mock_archiver,
    mock_diff_engine,
    mock_dag_manager,
    mock_architect_subagent,
    mock_glob,
    mock_isdir,
    mock_exists,
):
    mock_exists.return_value = True
    mock_isdir.return_value = True
    mock_glob.return_value = [
        f"{INBOX_DIR}/test_prd.md",
        f"{INBOX_DIR}/innocent_file.md",
    ]
    mock_file = MagicMock()
    mock_file.__enter__.return_value.read.return_value = "nodes:\n  test_prd.md:\n    description: This mentions innocent_file.md purely by chance."
    mock_open.return_value = mock_file
    mock_diff_instance = MagicMock()
    mock_diff_instance.calculate_diff.return_value = {}
    mock_diff_engine.return_value = mock_diff_instance
    plan_cmd(MagicMock())
    mock_architect_subagent.assert_awaited_once_with(
        [f"{INBOX_DIR}/test_prd.md", f"{INBOX_DIR}/innocent_file.md"]
    )
    archive_calls = [
        call[0][0] for call in mock_archiver.return_value.archive.call_args_list
    ]
    assert (
        f"{INBOX_DIR}/innocent_file.md" not in archive_calls
    ), "Functional Bug: innocent_file.md was archived because of loose substring matching in dag_content!"
