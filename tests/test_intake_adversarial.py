from pathlib import Path


def test_intake_agent_adversarial_security():
    agent_path = Path(__file__).parent.parent / ".agents/agents/sdlc_intake/agent.md"
    with open(agent_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert (
        "run_command" not in content
    ), "Agent has access to execute arbitrary commands"
    assert (
        "multi_replace_file_content" not in content
    ), "Agent has access to edit arbitrary files"
    assert (
        "intention-dag.yaml" in content and "never" in content.lower()
    ), "Agent is not explicitly restricted from DAG modification"
