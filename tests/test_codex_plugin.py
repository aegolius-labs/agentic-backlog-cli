import json
from pathlib import Path

import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "aio-agentic-sdlc"


def test_codex_plugin_manifest_and_marketplace_are_wired() -> None:
    manifest = json.loads(
        (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    marketplace = json.loads(
        (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
    )

    assert manifest["name"] == PLUGIN_ROOT.name
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./.mcp.json"
    assert any(
        entry["name"] == manifest["name"]
        and entry["source"]["path"] == "./plugins/aio-agentic-sdlc"
        for entry in marketplace["plugins"]
    )


def test_codex_plugin_mcp_uses_the_portable_uv_launcher() -> None:
    config = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = config["mcpServers"]["aio-agentic-sdlc"]

    assert server["command"] == "uvx"
    assert server["args"] == [
        "--from",
        "git+https://github.com/aegolius-labs/aio-agentic-sdlc",
        "aio-agentic-sdlc-mcp",
    ]


def test_codex_skill_has_valid_metadata_and_role_references() -> None:
    skill_root = PLUGIN_ROOT / "skills" / "manage-sdlc"
    skill_text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    _, frontmatter, body = skill_text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)

    assert metadata.keys() == {"name", "description"}
    assert metadata["name"] == skill_root.name
    assert "MCP" in body

    required_roles = {
        "architect",
        "cartographer",
        "devops",
        "implementer",
        "intake",
        "linter",
        "orchestrator",
        "qa",
        "researcher",
        "scribe",
    }
    assert {
        path.stem for path in (skill_root / "references" / "roles").glob("*.md")
    } == required_roles


def test_codex_skill_routes_intent_ir_through_protected_tools() -> None:
    skill_root = PLUGIN_ROOT / "skills" / "manage-sdlc"
    tools = (skill_root / "references" / "tools.md").read_text(encoding="utf-8")
    intake = (skill_root / "references" / "roles" / "intake.md").read_text(
        encoding="utf-8"
    )
    cartographer = (skill_root / "references" / "roles" / "cartographer.md").read_text(
        encoding="utf-8"
    )

    assert all(
        operation in tools
        for operation in (
            "create_intent_node",
            "set_intent",
            "validate_intent",
            "review_intent",
        )
    )
    assert "Intent IR v1" in intake
    assert "does not write" in intake.lower()
    assert "canonical DAG state" in intake
    assert "set_intent" in cartographer
    assert "do not patch DAG files" in cartographer


def test_codex_skill_routes_visual_review_before_mapping_approval() -> None:
    skill_root = PLUGIN_ROOT / "skills" / "manage-sdlc"
    tools = (skill_root / "references" / "tools.md").read_text(encoding="utf-8")
    cartographer = (skill_root / "references" / "roles" / "cartographer.md").read_text(
        encoding="utf-8"
    )
    manifest = json.loads(
        (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    )

    assert "visualize_dag" in tools
    assert "dag-tool visualize" in tools
    assert cartographer.index("visualize_dag") < cartographer.index("approve_mapping")
    assert any(
        "visual" in prompt.casefold()
        for prompt in manifest["interface"]["defaultPrompt"]
    )
    assert (ROOT / "doc" / "dag-visualization.md").is_file()


def test_project_scoped_codex_agents_map_every_sdlc_role() -> None:
    agent_dir = ROOT / ".codex" / "agents"
    configs = {
        path.stem: tomllib.loads(path.read_text(encoding="utf-8"))
        for path in agent_dir.glob("*.toml")
    }
    required_agents = {
        "sdlc_architect",
        "sdlc_cartographer",
        "sdlc_devops",
        "sdlc_implementer",
        "sdlc_intake",
        "sdlc_linter",
        "sdlc_orchestrator",
        "sdlc_qa",
        "sdlc_researcher",
        "sdlc_scribe",
    }

    assert configs.keys() == required_agents
    for filename, config in configs.items():
        assert config["name"] == filename
        assert config["description"]
        assert config["developer_instructions"]
