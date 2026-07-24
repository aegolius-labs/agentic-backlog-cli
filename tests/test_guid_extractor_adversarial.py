import os
import tempfile

import pytest
from pydantic import ValidationError

from aio_agentic_sdlc.reality_dag_generator import RealityDAGGenerator


def test_python_malformed_hex_uuid_crash():
    with tempfile.TemporaryDirectory() as tmpdir:
        file_content = "# aio-sdlc-node: abcdef1234\ndef foo(): pass\n"
        with open(os.path.join(tmpdir, "main.py"), "w", encoding="utf-8") as f:
            f.write(file_content)

        generator = RealityDAGGenerator(root_dir=tmpdir, system_name="TestSystem")
        try:
            generator.generate()
        except ValidationError:
            pytest.fail(
                "RealityDAGGenerator crashed on malformed UUID due to strict validation!"
            )


def test_markdown_invalid_uuid_crash():
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = os.path.join(tmpdir, ".agents", "agents")
        os.makedirs(agents_dir, exist_ok=True)
        agent_content = """---
name: MalformedAgent
type: agent
metadata:
  node_id: not-a-uuid
---
"""
        with open(os.path.join(agents_dir, "bad.md"), "w", encoding="utf-8") as f:
            f.write(agent_content)

        generator = RealityDAGGenerator(root_dir=tmpdir, system_name="TestSystem")
        try:
            generator.generate()
        except ValidationError:
            pytest.fail("RealityDAGGenerator crashed on malformed UUID in markdown!")


def test_markdown_integer_uuid_crash():
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = os.path.join(tmpdir, ".agents", "agents")
        os.makedirs(agents_dir, exist_ok=True)
        agent_content = """---
name: IntAgent
type: agent
metadata:
  node_id: 12345
---
"""
        with open(os.path.join(agents_dir, "bad.md"), "w", encoding="utf-8") as f:
            f.write(agent_content)

        generator = RealityDAGGenerator(root_dir=tmpdir, system_name="TestSystem")
        try:
            generator.generate()
        except AttributeError:
            pytest.fail("RealityDAGGenerator crashed on integer UUID in markdown!")
