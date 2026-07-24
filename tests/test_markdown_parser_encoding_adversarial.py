import os
import tempfile

from aio_agentic_sdlc.reality_dag_generator import RealityDAGGenerator


def test_markdown_parser_invalid_encoding():
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = os.path.join(tmpdir, ".agents", "agents", "bad_encoding")
        os.makedirs(agents_dir, exist_ok=True)
        # Create a non-utf8 binary file that has .md extension
        bad_file = os.path.join(agents_dir, "agent.md")
        with open(bad_file, "wb") as f:
            f.write(b"\x80\x81\x82---")

        generator = RealityDAGGenerator(root_dir=tmpdir, system_name="TestSystem")

        # This should NOT crash; UnicodeDecodeError should be caught gracefully
        try:
            generator.generate()
        except UnicodeDecodeError:
            assert False, "UnicodeDecodeError was not caught"
        else:
            assert True
