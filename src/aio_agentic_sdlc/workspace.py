"""Canonical project-local paths for AIO Agentic SDLC artifacts and state."""

from __future__ import annotations

from pathlib import Path

WORKSPACE_DIR = ".aio-agentic-sdlc"

INTENTION_DAG_FILE = f"{WORKSPACE_DIR}/intention-dag.yaml"
REALITY_DAG_FILE = f"{WORKSPACE_DIR}/reality-dag.yaml"
BACKLOG_FILE = f"{WORKSPACE_DIR}/backlog.json"
CONFIG_FILE = f"{WORKSPACE_DIR}/config.json"
AUDIT_FILE = f"{WORKSPACE_DIR}/state-audit.jsonl"
STATE_LOCK_FILE = f"{WORKSPACE_DIR}/state.lock"
MAPPING_LOCK_FILE = f"{WORKSPACE_DIR}/mapping.lock"
LEGACY_DIR = f"{WORKSPACE_DIR}/legacy"

INBOX_DIR = f"{WORKSPACE_DIR}/inbox"
SPECS_DIR = f"{WORKSPACE_DIR}/specs"
CHANGES_DIR = f"{WORKSPACE_DIR}/changes"
ARCHIVE_DIR = f"{WORKSPACE_DIR}/archive"
RESEARCH_SPIKES_DIR = f"{WORKSPACE_DIR}/research-spikes"

OPERATIONAL_DIRECTORIES = (
    INBOX_DIR,
    SPECS_DIR,
    CHANGES_DIR,
    ARCHIVE_DIR,
    RESEARCH_SPIKES_DIR,
)


def workspace_path(project_path: str | Path = ".", *parts: str) -> Path:
    """Return a path inside the canonical project-local framework workspace."""

    return Path(project_path) / WORKSPACE_DIR / Path(*parts)


def ensure_workspace(project_path: str | Path = ".") -> Path:
    """Create the canonical framework workspace and operational directories."""

    root = workspace_path(project_path)
    for relative in OPERATIONAL_DIRECTORIES:
        (Path(project_path) / relative).mkdir(parents=True, exist_ok=True)
    return root
