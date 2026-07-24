from unittest.mock import MagicMock, patch


@patch("os.path.exists")
@patch("os.path.isdir")
@patch("glob.glob")
@patch("asyncio.run")
@patch("aio_agentic_sdlc.dag_manager.DAGManager")
@patch("aio_agentic_sdlc.diffing_engine.DiffingEngine")
@patch("aio_agentic_sdlc.archiver.PRDArchiver")
@patch("builtins.open", new_callable=MagicMock)
def test_cli_unconditional_archival_edge_case(
    mock_open,
    mock_archiver,
    mock_diff_engine,
    mock_dag_manager,
    mock_asyncio_run,
    mock_glob,
    mock_isdir,
    mock_exists,
):
    from aio_agentic_sdlc.cli import plan_cmd

    mock_exists.return_value = True
    mock_isdir.return_value = True
    mock_glob.return_value = ["inbox/test_prd.md", "inbox/innocent_file.md"]
    mock_file = MagicMock()
    mock_file.__enter__.return_value.read.return_value = "nodes:\n  test_prd.md:\n    description: This mentions innocent_file.md purely by chance."
    mock_open.return_value = mock_file
    mock_diff_instance = MagicMock()
    mock_diff_instance.calculate_diff.return_value = {}
    mock_diff_engine.return_value = mock_diff_instance
    plan_cmd(MagicMock())
    archive_calls = [
        call[0][0] for call in mock_archiver.return_value.archive.call_args_list
    ]
    assert (
        "inbox/innocent_file.md" not in archive_calls
    ), "Functional Bug: innocent_file.md was archived because of loose substring matching in dag_content!"
