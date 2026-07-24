"""Tests for framework detection and seed generation."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aio_agentic_sdlc.detect import detect_frameworks, generate_seed_backlog


class TestDetectFrameworks:
    def test_detect_python(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]")
        assert detect_frameworks(str(tmp_path)) == ["python"]

    def test_detect_python_uv(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.uv]")
        assert "uv" in detect_frameworks(str(tmp_path))

    def test_detect_node_npm(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        frameworks = detect_frameworks(str(tmp_path))
        assert "node" in frameworks
        assert "npm" in frameworks

    def test_detect_node_yarn(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "yarn.lock").write_text("")
        frameworks = detect_frameworks(str(tmp_path))
        assert "node" in frameworks
        assert "yarn" in frameworks

    def test_detect_rust(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("")
        assert "rust" in detect_frameworks(str(tmp_path))

    def test_detect_multiple(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.uv]")
        (tmp_path / "package.json").write_text("{}")
        frameworks = detect_frameworks(str(tmp_path))
        assert "node" in frameworks
        assert "npm" in frameworks
        assert "python" in frameworks
        assert "uv" in frameworks


class TestGenerateSeedBacklog:
    def test_generate_universal(self):
        items = generate_seed_backlog([])
        assert "Initial Project Documentation" in items

    def test_generate_python(self):
        items = generate_seed_backlog(["python"])
        assert "Initial Project Documentation" in items
        assert "Configure Pytest infrastructure" in items

    def test_generate_node(self):
        items = generate_seed_backlog(["node", "npm"])
        assert "Initial Project Documentation" in items
        assert "Configure ESLint/Prettier" in items
        assert "Setup CI/CD Pipeline (Node)" in items

    def test_generate_rust(self):
        items = generate_seed_backlog(["rust"])
        assert "Initial Project Documentation" in items
        assert "Configure Clippy and Rustfmt" in items

    def test_generate_openspec(self, tmp_path):
        (tmp_path / "tasks.md").write_text(
            "- [ ] OpenSpec task 1\n- [x] OpenSpec task 2"
        )
        items = generate_seed_backlog([], cwd=str(tmp_path))
        assert "OpenSpec task 1" in items
        assert items["OpenSpec task 1"]["status"] == "New"
        assert items["OpenSpec task 1"]["category"] == "Open-Spec Task"
        assert "OpenSpec task 2" in items
        assert items["OpenSpec task 2"]["status"] == "Completed"
        assert "Initial Project Documentation" not in items

    def test_generate_speckit(self, tmp_path):
        specs_dir = tmp_path / "specs"
        specs_dir.mkdir()
        (specs_dir / "tasks.md").write_text("- [ ] SpecKit task 1")
        items = generate_seed_backlog([], cwd=str(tmp_path))
        assert "SpecKit task 1" in items
        assert items["SpecKit task 1"]["category"] == "Spec-Kit Task (tasks.md)"
        assert "Initial Project Documentation" not in items


class TestInitCmdIntegration:
    @pytest.fixture(autouse=True)
    def clean_backlog(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("builtins.input", lambda *args: "1")

    def test_init_empty(self):
        import argparse

        from aio_agentic_sdlc.cli import init_cmd, load_backlog

        # Use empty flag to override detection
        init_cmd(argparse.Namespace(empty=True))
        data = load_backlog()
        assert data["nodes"] == {}

    def test_init_with_detection(self, tmp_path):
        import argparse

        from aio_agentic_sdlc.cli import init_cmd, load_backlog

        (tmp_path / "pyproject.toml").write_text("")
        # Call without empty flag, should detect python
        init_cmd(argparse.Namespace(empty=False))
        data = load_backlog()
        assert "Initial Project Documentation" in data["nodes"]
        assert "Configure Pytest infrastructure" in data["nodes"]
