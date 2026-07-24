"""Tests for the status tracking feature."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aio_agentic_sdlc.cli import (
    _get_status,
    load_backlog,
    save_backlog,
)


@pytest.fixture(autouse=True)
def clean_backlog(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _make_item(impact, effort, status="New", requires=None, **extra):
    item = {
        "impact": impact,
        "effort": effort,
        "category": extra.get("category", "Business Value"),
        "requires": requires or [],
        "ai_driven": False,
        "status": status,
        "scores": {},
    }
    item.update(extra)
    return item


def _load():
    data = load_backlog()
    nodes = data.get("nodes", {})
    edges = data.get("edges", [])
    items = {}
    for name, node in nodes.items():
        item = node.copy()
        item["requires"] = [
            e["to"] for e in edges if e["from"] == name and e["relation"] == "requires"
        ]
        parent_edges = [
            e["to"] for e in edges if e["from"] == name and e["relation"] == "parent"
        ]
        item["parent_id"] = parent_edges[0] if parent_edges else None
        items[name] = item
    return {"items": items}


def _save(items_dict):
    nodes = {}
    edges = []
    for name, item in items_dict.items():
        node = item.copy()
        if "requires" in node:
            for req in node["requires"]:
                edges.append({"from": name, "to": req, "relation": "requires"})
            del node["requires"]
        if "parent_id" in node and node["parent_id"]:
            edges.append({"from": name, "to": node["parent_id"], "relation": "parent"})
            del node["parent_id"]
        if "item_type" not in node:
            node["item_type"] = "Task"
        nodes[name] = node
    save_backlog({"nodes": nodes, "edges": edges})


def _run_prioritize():
    import argparse

    from aio_agentic_sdlc.cli import prioritize_cmd

    prioritize_cmd(argparse.Namespace())


# ── backward compatibility ───────────────────────────────────────────────────


class TestBackwardCompat:
    def test_missing_status_defaults_to_new(self):
        """Items without a status field should be treated as 'New'."""
        item = {
            "impact": 3,
            "effort": 3,
            "category": "Business Value",
            "requires": [],
            "ai_driven": False,
            "scores": {},
        }
        assert _get_status(item) == "New"

    def test_explicit_status_is_respected(self):
        item = _make_item(3, 3, status="In Progress")
        assert _get_status(item) == "In Progress"


# ── completed items zero scoring ─────────────────────────────────────────────


class TestCompletedScoring:
    def test_completed_item_gets_zero_scores(self):
        _save(
            {
                "done": _make_item(5, 1, status="Completed"),
                "todo": _make_item(3, 3, status="New"),
            }
        )
        _run_prioritize()
        data = _load()
        assert data["items"]["done"]["scores"]["base"] == 0
        assert data["items"]["done"]["scores"]["final"] == 0
        # Non-completed item should still have real scores
        assert data["items"]["todo"]["scores"]["base"] > 0

    def test_completed_item_sinks_to_bottom(self):
        _save(
            {
                "done": _make_item(5, 1, status="Completed"),
                "todo": _make_item(1, 5, status="New"),
            }
        )
        _run_prioritize()
        data = _load()
        keys = list(data["items"].keys())
        assert keys.index("todo") < keys.index("done")


# ── status_cmd ───────────────────────────────────────────────────────────────


class TestStatusCmd:
    def test_status_cmd_changes_status(self):
        import argparse

        from aio_agentic_sdlc.cli import status_cmd

        _save({"alpha": _make_item(3, 3, status="New")})
        status_cmd(argparse.Namespace(name="alpha", new_status="In Progress"))
        data = _load()
        assert data["items"]["alpha"]["status"] == "In Progress"

    def test_status_cmd_missing_item(self):
        import argparse

        from aio_agentic_sdlc.cli import status_cmd

        _save({})
        with pytest.raises(SystemExit):
            status_cmd(argparse.Namespace(name="nope", new_status="Completed"))


# ── add_cmd with status ──────────────────────────────────────────────────────


class TestAddWithStatus:
    def test_add_default_status(self):
        import argparse

        from aio_agentic_sdlc.cli import add_cmd

        _save({})
        add_cmd(
            argparse.Namespace(
                name="feat",
                impact=3,
                effort=3,
                category="Business",
                description="Valid description",
                requires=None,
                ai_driven=False,
                status="New",
                blockers=None,
            )
        )
        data = _load()
        assert data["items"]["feat"]["status"] == "New"

    def test_add_custom_status(self):
        import argparse

        from aio_agentic_sdlc.cli import add_cmd

        _save({})
        add_cmd(
            argparse.Namespace(
                name="wip",
                impact=3,
                effort=3,
                category="Business",
                description="Valid description",
                requires=None,
                ai_driven=False,
                status="In Progress",
                blockers=None,
            )
        )
        data = _load()
        assert data["items"]["wip"]["status"] == "In Progress"

    def test_add_missing_description_raises(self):
        import argparse

        from aio_agentic_sdlc.cli import add_cmd

        _save({})
        with pytest.raises(ValueError, match="Description cannot be empty"):
            add_cmd(
                argparse.Namespace(
                    name="wip",
                    impact=3,
                    effort=3,
                    category="Business",
                    description="",
                    requires=None,
                    ai_driven=False,
                    status="In Progress",
                    blockers=None,
                )
            )
