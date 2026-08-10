from pathlib import Path

from aio_agentic_sdlc.workspace import (
    ARCHIVE_DIR,
    BACKLOG_FILE,
    CHANGES_DIR,
    CONFIG_FILE,
    INBOX_DIR,
    INTENTION_DAG_FILE,
    REALITY_DAG_FILE,
    RESEARCH_SPIKES_DIR,
    SPECS_DIR,
    WORKSPACE_DIR,
    ensure_workspace,
    workspace_path,
)


def test_framework_paths_share_the_full_project_name_parent():
    assert WORKSPACE_DIR == ".aio-agentic-sdlc"
    assert INTENTION_DAG_FILE == ".aio-agentic-sdlc/intention-dag.yaml"
    assert REALITY_DAG_FILE == ".aio-agentic-sdlc/reality-dag.yaml"
    assert BACKLOG_FILE == ".aio-agentic-sdlc/backlog.json"
    assert CONFIG_FILE == ".aio-agentic-sdlc/config.json"
    assert INBOX_DIR == ".aio-agentic-sdlc/inbox"
    assert SPECS_DIR == ".aio-agentic-sdlc/specs"
    assert CHANGES_DIR == ".aio-agentic-sdlc/changes"
    assert ARCHIVE_DIR == ".aio-agentic-sdlc/archive"
    assert RESEARCH_SPIKES_DIR == ".aio-agentic-sdlc/research-spikes"


def test_workspace_path_is_project_relative(tmp_path):
    assert workspace_path(tmp_path, "specs", "feature.md") == (
        tmp_path / ".aio-agentic-sdlc" / "specs" / "feature.md"
    )


def test_ensure_workspace_eagerly_creates_operational_directories(tmp_path):
    root = ensure_workspace(tmp_path)

    assert root == tmp_path / ".aio-agentic-sdlc"
    for relative in ("inbox", "specs", "changes", "archive", "research-spikes"):
        assert (root / relative).is_dir()
    assert not (root / "intention-dag.yaml").exists()
    assert not (root / "reality-dag.yaml").exists()


def test_no_short_name_state_directory_is_created(tmp_path):
    ensure_workspace(tmp_path)

    assert not (Path(tmp_path) / ".aio-sdlc").exists()
