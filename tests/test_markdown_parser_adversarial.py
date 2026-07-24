import os
import tempfile

from aio_agentic_sdlc.reality_dag_generator import RealityDAGGenerator


def test_markdown_parser_realistic_agent_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = os.path.join(tmpdir, ".agents", "agents", "sdlc_architect")
        os.makedirs(agents_dir, exist_ok=True)
        # Realistic agent without 'type: agent'
        agent_content = """---
name: "sdlc_architect"
description: "Subagent responsible for software architecture research"
tools:
  - view_file
---
# Body
"""
        with open(os.path.join(agents_dir, "agent.md"), "w", encoding="utf-8") as f:
            f.write(agent_content)

        generator = RealityDAGGenerator(root_dir=tmpdir, system_name="TestSystem")
        dag = generator.generate()

        agent_nodes = [
            n
            for n in dag.nodes.values()
            if getattr(n, "type", None) and getattr(n.type, "name", None) == "AGENT"
        ]

        assert (
            len(agent_nodes) == 1
        ), "Agent was not extracted because 'type: agent' is missing in frontmatter"
