"""Tests for the next command."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aio_agentic_sdlc.cli import save_backlog


@pytest.fixture(autouse=True)
def clean_backlog(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _make_item(impact, effort, status="New", blockers=None, requires=None, **extra):
    item = {
        "impact": impact,
        "effort": effort,
        "category": extra.get("category", "Business Value"),
        "requires": requires or [],
        "ai_driven": False,
        "status": status,
        "blockers": blockers or [],
        "scores": {},
    }
    item.update(extra)
    return item


def _save(items_dict):
    save_backlog({"items": items_dict})


def _run_next(format="json"):
    import argparse
    from io import StringIO

    from aio_agentic_sdlc.cli import next_cmd

    old_stdout = sys.stdout
    sys.stdout = StringIO()
    try:
        next_cmd(argparse.Namespace(format=format))
        output = sys.stdout.getvalue()
    finally:
        sys.stdout = old_stdout

    if format == "json":
        return json.loads(output)
    return output


class TestNextCmd:
    def test_next_empty(self):
        _save({})
        result = _run_next()
        assert result["target"] is None
        assert "empty" in result["warning"]

    def test_next_simple(self):
        _save({"feat": _make_item(5, 1)})
        result = _run_next()
        assert result["target"]["name"] == "feat"
        assert "warning" not in result

    def test_next_skips_completed(self):
        _save(
            {
                "alpha": _make_item(5, 1, status="Completed"),
                "beta": _make_item(3, 3),
            }
        )
        result = _run_next()
        assert result["target"]["name"] == "beta"
        assert "warning" not in result  # Only warn for blockers, not normal completion

    def test_next_skips_blocked(self):
        _save(
            {
                "alpha": _make_item(5, 1, status="Blocked", blockers=["API down"]),
                "beta": _make_item(3, 3),
            }
        )
        result = _run_next()
        assert result["target"]["name"] == "beta"
        assert "warning" in result
        assert "alpha" in result["warning"]
        assert "API down" in result["warning"]

    def test_next_all_unworkable(self):
        _save(
            {
                "alpha": _make_item(5, 1, status="Completed"),
                "beta": _make_item(3, 3, status="Blocked", blockers=["wait"]),
            }
        )
        result = _run_next()
        assert result["target"] is None
        assert "No workable items remain" in result["warning"]

    def test_next_human_format(self):
        _save({"feat": _make_item(5, 1, category="Security")})
        output = _run_next(format="human")
        assert "Next workable item: feat" in output
        assert "Security" in output
