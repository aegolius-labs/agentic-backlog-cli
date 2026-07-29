from unittest.mock import AsyncMock, MagicMock, patch

from aio_agentic_sdlc.cli import main


def test_cli_plan(capsys):
    with patch("sys.argv", ["cli", "plan"]):
        with patch("aio_agentic_sdlc.cli.plan_cmd") as mock_plan:
            try:
                main()
            except SystemExit:
                pass
            mock_plan.assert_called_once()


@patch("os.path.exists")
@patch("os.path.isdir")
@patch("glob.glob")
@patch("aio_agentic_sdlc.cli._run_architect_subagent", new_callable=AsyncMock)
@patch("aio_agentic_sdlc.dag_manager.DAGManager")
@patch("aio_agentic_sdlc.diffing_engine.DiffingEngine")
@patch("aio_agentic_sdlc.archiver.PRDArchiver")
@patch("builtins.open", new_callable=MagicMock)
def test_plan_cmd_with_inbox_files(
    mock_open,
    mock_archiver,
    mock_diff_engine,
    mock_dag_manager,
    mock_architect_subagent,
    mock_glob,
    mock_isdir,
    mock_exists,
):
    from aio_agentic_sdlc.cli import plan_cmd

    mock_exists.return_value = True
    mock_isdir.return_value = True
    mock_glob.return_value = ["inbox/prd1.md", "inbox/prd2.md", "inbox/prd3.md"]

    # Mock open to return a file containing 'prd1.md' and 'prd3.md' as valid YAML nodes
    mock_file = MagicMock()
    mock_file.__enter__.return_value.read.return_value = (
        "nodes:\n  - id: prd1.md\n  - id: prd3.md"
    )
    mock_open.return_value = mock_file

    mock_diff_instance = MagicMock()
    mock_diff_instance.calculate_diff.return_value = {"nodes": [], "edges": []}
    mock_diff_engine.return_value = mock_diff_instance

    # Make prd3.md raise an exception when archived to test that the loop continues
    def mock_archive_side_effect(file_path):
        if file_path == "inbox/prd3.md":
            raise ValueError("Test error")

    mock_archiver.return_value.archive.side_effect = mock_archive_side_effect

    plan_cmd(MagicMock())

    mock_architect_subagent.assert_awaited_once_with(
        ["inbox/prd1.md", "inbox/prd2.md", "inbox/prd3.md"]
    )
    # Should archive prd1.md, try prd3.md (fails), skip prd2.md
    mock_archiver.return_value.archive.assert_any_call("inbox/prd1.md")
    mock_archiver.return_value.archive.assert_any_call("inbox/prd3.md")

    # Check that prd2.md was NOT archived
    archive_calls = [
        call[0][0] for call in mock_archiver.return_value.archive.call_args_list
    ]
    assert "inbox/prd2.md" not in archive_calls

    mock_diff_engine.assert_called_once()
    mock_diff_instance.calculate_diff.assert_called_once()


@patch("os.path.exists")
@patch("aio_agentic_sdlc.dag_manager.DAGManager")
@patch("aio_agentic_sdlc.diffing_engine.DiffingEngine")
def test_plan_cmd_without_inbox_files(mock_diff_engine, mock_dag_manager, mock_exists):
    from aio_agentic_sdlc.cli import plan_cmd

    mock_exists.return_value = False

    mock_diff_instance = MagicMock()
    mock_diff_instance.calculate_diff.return_value = {"nodes": [], "edges": []}
    mock_diff_engine.return_value = mock_diff_instance

    plan_cmd(MagicMock())

    mock_diff_engine.assert_called_once()
    mock_diff_instance.calculate_diff.assert_called_once()


def test_cli_apply(capsys):
    with patch("sys.argv", ["cli", "apply"]):
        with patch("aio_agentic_sdlc.cli.apply_cmd") as mock_apply:
            try:
                main()
            except SystemExit:
                pass
            mock_apply.assert_called_once()
