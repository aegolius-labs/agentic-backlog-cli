import json
import os

from aio_agentic_sdlc.mcp_server import generate_document


def test_mcp_arbitrary_file_write_vulnerability(tmp_path):
    # This simulates a user picking a target dir OUTSIDE the workspace
    # and the mcp_server allowing it because the output_path check
    # only checks if output_path is within target_dir, but target_dir itself
    # can be absolutely anything.

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Create templates dir in workspace so template engine can find it if cwd is workspace
    # Actually wait, templating engine uses get_project_root() / "templates" or cwd() / "templates"
    templates_dir = workspace / "templates"
    templates_dir.mkdir()
    template_file = templates_dir / "test_template.md"
    template_file.write_text("Hello {{ name }}")

    # The malicious target is OUTSIDE the workspace
    malicious_target_dir = tmp_path / "system32_simulation"
    malicious_target_dir.mkdir()

    # Run the function simulating we are in the workspace
    original_cwd = os.getcwd()
    os.chdir(str(workspace))
    try:
        data_json = json.dumps({"name": "World"})
        result = generate_document(
            template_name="test_template.md",
            data_json=data_json,
            output_filename="hacked.md",
            target_dir=str(malicious_target_dir),  # Outside workspace!
        )

        hacked_file = malicious_target_dir / "hacked.md"
        assert "outside of the project root" in result
        assert (
            not hacked_file.exists()
        ), f"VULNERABILITY: Arbitrary File Write. Output was written to {hacked_file}"
    finally:
        os.chdir(original_cwd)
