import yaml


def test_no_excessive_permissions():
    agent_path = ".agents/agents/sdlc_intake/agent.md"
    with open(agent_path, "r", encoding="utf-8") as f:
        parts = f.read().split("---")
    frontmatter = yaml.safe_load(parts[1])
    tools = frontmatter.get("tools", [])
    assert (
        "run_command" not in tools
    ), "Security vulnerability: Intake agent has run_command"
    assert (
        "multi_replace_file_content" not in tools
    ), "Security vulnerability: Intake agent has multi_replace_file_content"


def test_grep_search_in_tools():
    agent_path = ".agents/agents/sdlc_intake/agent.md"
    with open(agent_path, "r", encoding="utf-8") as f:
        parts = f.read().split("---")
    frontmatter = yaml.safe_load(parts[1])
    assert "grep_search" in frontmatter.get(
        "tools", []
    ), "grep_search tool is missing from tools"
