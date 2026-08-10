import argparse
import json
import sys

import pytest

from aio_agentic_sdlc import core
from aio_agentic_sdlc.cli import init_cmd, main
from aio_agentic_sdlc.workspace import BACKLOG_FILE, CONFIG_FILE, WORKSPACE_DIR


def test_cli_has_no_github_sync_surface(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["aio-sdlc", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "sync" not in help_text
    assert "GitHub mode" not in help_text


def test_init_rejects_removed_github_option(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["aio-sdlc", "init", "--github"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    assert "unrecognized arguments: --github" in capsys.readouterr().err


def test_legacy_github_config_cannot_redirect_backlog_operations(tmp_path):
    (tmp_path / ".aio-agentic-sdlc.json").write_text(
        json.dumps(
            {
                "core": {"mode": "github"},
                "github": {"repo": "example/project", "project_number": 1},
            }
        ),
        encoding="utf-8",
    )

    core.add_item(
        "Local task",
        impact=5,
        effort=1,
        category="Reliability",
        description="Prove that all state mutations remain in the workspace.",
        project_path=str(tmp_path),
    )

    backlog = json.loads((tmp_path / BACKLOG_FILE).read_text(encoding="utf-8"))
    assert "Local task" in backlog["nodes"]


def test_init_records_local_as_the_only_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda *_args: "1")

    init_cmd(argparse.Namespace(empty=True, platforms=None))

    config = json.loads((tmp_path / CONFIG_FILE).read_text(encoding="utf-8"))
    assert config["core"]["mode"] == "local"
    assert "github" not in config


def test_failed_backlog_write_preserves_previous_state(tmp_path, monkeypatch):
    from aio_agentic_sdlc import state

    original = {
        "nodes": {
            "Existing": {
                "description": "This state must survive a failed replacement.",
            }
        },
        "edges": [],
    }
    core.save_backlog(original, str(tmp_path))

    def fail_dump(*_args, **_kwargs):
        raise OSError("simulated interrupted write")

    monkeypatch.setattr(state.json, "dumps", fail_dump)
    replacement = core.load_backlog(str(tmp_path))
    replacement["nodes"] = {}

    with pytest.raises(OSError, match="simulated interrupted write"):
        core.save_backlog(replacement, str(tmp_path))

    assert core.load_backlog(str(tmp_path))["nodes"] == original["nodes"]
    assert list((tmp_path / WORKSPACE_DIR).glob(".backlog.json.*.tmp")) == []
