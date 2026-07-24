"""Tests for the blocker awareness feature."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aio_agentic_sdlc.cli import (
    _get_blockers,
    load_backlog,
    save_backlog,
)


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


class TestBlockerBackwardCompat:
    def test_missing_blockers_defaults_to_empty(self):
        item = {
            "impact": 3,
            "effort": 3,
            "category": "X",
            "requires": [],
            "ai_driven": False,
            "scores": {},
        }
        assert _get_blockers(item) == []


# ── blockers do NOT change scores ────────────────────────────────────────────


class TestBlockerScoring:
    def test_blocked_item_retains_score(self):
        """Blockers flag items as unworkable but do NOT change math."""
        _save(
            {
                "alpha": _make_item(5, 1, status="New", blockers=["waiting on vendor"]),
                "beta": _make_item(5, 1, status="New"),
            }
        )
        _run_prioritize()
        data = _load()
        # Both have identical impact/effort, so both should have the same scores
        assert (
            data["items"]["alpha"]["scores"]["base"]
            == data["items"]["beta"]["scores"]["base"]
        )

    def test_blocked_item_auto_status(self):
        """During prioritize, items with blockers auto-set to Blocked."""
        _save(
            {
                "alpha": _make_item(5, 1, status="New", blockers=["reason"]),
            }
        )
        _run_prioritize()
        data = _load()
        assert data["items"]["alpha"]["status"] == "Blocked"

    def test_unblocked_item_reverts_status(self):
        """During prioritize, Blocked items with no blockers revert to New."""
        _save(
            {
                "alpha": _make_item(5, 1, status="Blocked", blockers=[]),
            }
        )
        _run_prioritize()
        data = _load()
        assert data["items"]["alpha"]["status"] == "New"


# ── block_cmd ────────────────────────────────────────────────────────────────


class TestBlockCmd:
    def test_block_adds_blocker_and_sets_status(self):
        import argparse

        from aio_agentic_sdlc.cli import block_cmd

        _save({"feat": _make_item(3, 3)})
        block_cmd(argparse.Namespace(name="feat", reason="API key pending"))
        data = _load()
        assert "API key pending" in data["items"]["feat"]["blockers"]
        assert data["items"]["feat"]["status"] == "Blocked"

    def test_block_no_duplicate(self):
        import argparse

        from aio_agentic_sdlc.cli import block_cmd

        _save({"feat": _make_item(3, 3, blockers=["reason"])})
        block_cmd(argparse.Namespace(name="feat", reason="reason"))
        data = _load()
        assert data["items"]["feat"]["blockers"].count("reason") == 1

    def test_block_missing_item(self):
        import argparse

        from aio_agentic_sdlc.cli import block_cmd

        _save({})
        with pytest.raises(SystemExit):
            block_cmd(argparse.Namespace(name="nope", reason="x"))


# ── unblock_cmd ──────────────────────────────────────────────────────────────


class TestUnblockCmd:
    def test_unblock_removes_blocker(self):
        import argparse

        from aio_agentic_sdlc.cli import unblock_cmd

        _save(
            {
                "feat": _make_item(
                    3, 3, status="Blocked", blockers=["reason1", "reason2"]
                )
            }
        )
        unblock_cmd(argparse.Namespace(name="feat", reason="reason1"))
        data = _load()
        assert "reason1" not in data["items"]["feat"]["blockers"]
        assert "reason2" in data["items"]["feat"]["blockers"]
        # Still blocked because reason2 remains
        assert data["items"]["feat"]["status"] == "Blocked"

    def test_unblock_last_reverts_status(self):
        import argparse

        from aio_agentic_sdlc.cli import unblock_cmd

        _save({"feat": _make_item(3, 3, status="Blocked", blockers=["only-blocker"])})
        unblock_cmd(argparse.Namespace(name="feat", reason="only-blocker"))
        data = _load()
        assert data["items"]["feat"]["blockers"] == []
        assert data["items"]["feat"]["status"] == "New"

    def test_unblock_missing_item(self):
        import argparse

        from aio_agentic_sdlc.cli import unblock_cmd

        _save({})
        with pytest.raises(SystemExit):
            unblock_cmd(argparse.Namespace(name="nope", reason="x"))
