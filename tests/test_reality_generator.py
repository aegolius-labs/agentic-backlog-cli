import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from aio_agentic_sdlc.dag_models import EdgeType, NodeType
from aio_agentic_sdlc.reality_dag_generator import RealityDAGGenerator


def test_reality_generator_basic():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a sample python file
        file_content = """
import os
from datetime import datetime

class UserModel(BaseModel):
    pass

class UserService:
    def __init__(self):
        pass
        
    def get_user(self):
        pass

@app.get('/users')
def list_users():
    pass
"""
        with open(os.path.join(tmpdir, "main.py"), "w", encoding="utf-8") as f:
            f.write(file_content)

        generator = RealityDAGGenerator(root_dir=tmpdir, system_name="TestSystem")
        dag = generator.generate()

        # Verify nodes
        node_ids = {n.id: n for n in dag.nodes.values()}

        assert generator._id_to_uuid("system_root") in node_ids
        assert node_ids[generator._id_to_uuid("system_root")].type == NodeType.SYSTEM

        assert generator._id_to_uuid("main") in node_ids
        assert node_ids[generator._id_to_uuid("main")].type == NodeType.MODULE

        assert generator._id_to_uuid("main.UserModel") in node_ids
        assert node_ids[generator._id_to_uuid("main.UserModel")].type == NodeType.ENTITY

        assert generator._id_to_uuid("main.UserService") in node_ids
        assert (
            node_ids[generator._id_to_uuid("main.UserService")].type
            == NodeType.COMPONENT
        )

        assert generator._id_to_uuid("main.UserService.get_user") in node_ids
        assert (
            node_ids[generator._id_to_uuid("main.UserService.get_user")].type
            == NodeType.COMPONENT
        )

        assert generator._id_to_uuid("main.list_users") in node_ids
        assert (
            node_ids[generator._id_to_uuid("main.list_users")].type == NodeType.ENDPOINT
        )

        # Verify edges
        edges = dag.edges

        def has_edge(source, target, type):
            return any(
                e.source == source and e.target == target and e.type == type
                for e in edges
            )

        assert has_edge(
            generator._id_to_uuid("system_root"),
            generator._id_to_uuid("main"),
            EdgeType.CONTAINS,
        )
        assert has_edge(
            generator._id_to_uuid("main"),
            generator._id_to_uuid("main.UserModel"),
            EdgeType.CONTAINS,
        )
        assert has_edge(
            generator._id_to_uuid("main"),
            generator._id_to_uuid("main.UserService"),
            EdgeType.CONTAINS,
        )
        assert has_edge(
            generator._id_to_uuid("main.UserService"),
            generator._id_to_uuid("main.UserService.get_user"),
            EdgeType.CONTAINS,
        )
        assert has_edge(
            generator._id_to_uuid("main"),
            generator._id_to_uuid("main.list_users"),
            EdgeType.CONTAINS,
        )

        # Depends on
        assert not has_edge("main", "os", EdgeType.DEPENDS_ON)
        assert not has_edge("main", "datetime", EdgeType.DEPENDS_ON)


def test_reality_generator_depends_on():
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "utils.py"), "w", encoding="utf-8") as f:
            f.write("def helper(): pass\n")

        with open(os.path.join(tmpdir, "main.py"), "w", encoding="utf-8") as f:
            f.write("import utils\n")

        generator = RealityDAGGenerator(root_dir=tmpdir)
        dag = generator.generate()

        def has_edge(source, target, type):
            return any(
                e.source == source and e.target == target and e.type == type
                for e in dag.edges
            )

        assert has_edge(
            generator._id_to_uuid("main"),
            generator._id_to_uuid("utils"),
            EdgeType.DEPENDS_ON,
        )


def test_reality_generator_agents():
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = os.path.join(tmpdir, ".agents", "agents")
        os.makedirs(agents_dir, exist_ok=True)
        agent_content = """---
name: ArchitectAgent
type: agent
description: An agent that designs architecture.
---
# Some body
"""
        with open(os.path.join(agents_dir, "architect.md"), "w", encoding="utf-8") as f:
            f.write(agent_content)

        generator = RealityDAGGenerator(root_dir=tmpdir, system_name="TestSystem")
        dag = generator.generate()

        node_ids = {n.id: n for n in dag.nodes.values()}

        agent_id = generator._id_to_uuid("ArchitectAgent")
        assert agent_id in node_ids
        assert node_ids[agent_id].type == NodeType.AGENT


def test_reality_generator_python_guid_extraction():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a sample python file with GUID comment
        file_content = """# aio-sdlc-node: 2e8a1562-7e77-4402-992f-f461e8c7161f
import os

class UserModel:
    pass
"""
        with open(os.path.join(tmpdir, "main.py"), "w", encoding="utf-8") as f:
            f.write(file_content)

        generator = RealityDAGGenerator(root_dir=tmpdir, system_name="TestSystem")
        dag = generator.generate()

        node_ids = {n.id: n for n in dag.nodes.values()}

        expected_uuid = "2e8a1562-7e77-4402-992f-f461e8c7161f"
        assert expected_uuid in node_ids
        assert node_ids[expected_uuid].type == NodeType.MODULE

        # We need to make sure the edge is also updated? Wait, _id_to_uuid handles everything.
        # But for classes, it prepends the parent ID.
        assert generator._id_to_uuid(f"{expected_uuid}.UserModel") in node_ids


def test_reality_generator_definition_guid_does_not_replace_module_identity():
    with tempfile.TemporaryDirectory() as tmpdir:
        expected_uuid = "2e8a1562-7e77-4402-992f-f461e8c7161f"
        file_content = f"""# aio-sdlc-node: {expected_uuid}
@registered
class UserModel:
    pass
"""
        source_path = os.path.join(tmpdir, "main.py")
        with open(source_path, "w", encoding="utf-8") as handle:
            handle.write(file_content)

        generator = RealityDAGGenerator(root_dir=tmpdir, system_name="TestSystem")
        dag = generator.generate()

        module_id = generator._id_to_uuid("main")
        assert module_id in dag.nodes
        assert dag.nodes[module_id].type == NodeType.MODULE
        assert expected_uuid in dag.nodes
        assert dag.nodes[expected_uuid].name == "UserModel"
        assert (
            generator.source_locations[expected_uuid][0].as_dict()["marker_line"] == 1
        )


def test_reality_generator_rejects_duplicate_canonical_source_markers(tmp_path):
    marker = "6506870b-b262-4f54-b6e9-43de4a873a55"
    (tmp_path / "one.py").write_text(
        f"# aio-sdlc-node: {marker}\nclass One:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "two.py").write_text(
        f"# aio-sdlc-node: {marker.upper()}\nclass Two:\n    pass\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError, match="source marker collides with existing identity"
    ):
        RealityDAGGenerator(str(tmp_path), "Duplicate marker test").generate()


def test_reality_generator_skips_nonstructural_expression_trees(tmp_path):
    path_expression = " / ".join(f'Path("segment-{index}")' for index in range(2_000))
    (tmp_path / "large_expression.py").write_text(
        f"CONFIG_PATH = {path_expression}\n\nclass AfterExpression:\n    pass\n",
        encoding="utf-8",
    )

    generated = RealityDAGGenerator(str(tmp_path), "Expression test").generate()

    assert any(node.name == "AfterExpression" for node in generated.nodes.values())


def test_reality_generator_excludes_framework_state_directories(tmp_path):
    (tmp_path / "source.py").write_text(
        "class IncludedSource:\n    pass\n",
        encoding="utf-8",
    )
    for state_directory in (".aio-agentic-sdlc", ".aio-sdlc"):
        state_path = tmp_path / state_directory
        state_path.mkdir()
        (state_path / "archived.py").write_text(
            "class ExcludedFrameworkState:\n    pass\n",
            encoding="utf-8",
        )

    generated = RealityDAGGenerator(str(tmp_path), "State exclusion test").generate()
    names = {node.name for node in generated.nodes.values()}

    assert "IncludedSource" in names
    assert "ExcludedFrameworkState" not in names


def test_reality_generator_excludes_framework_qa_sandbox(tmp_path):
    (tmp_path / "source.py").write_text(
        "class IncludedProjectSource:\n    pass\n",
        encoding="utf-8",
    )
    qa_sandbox = tmp_path / ".qa-sandbox"
    qa_sandbox.mkdir()
    (qa_sandbox / "adversarial_probe.py").write_text(
        "class IgnoredQAProbe:\n    pass\n",
        encoding="utf-8",
    )

    generated = RealityDAGGenerator(str(tmp_path), "QA exclusion test").generate()
    names = {node.name for node in generated.nodes.values()}

    assert "IncludedProjectSource" in names
    assert "IgnoredQAProbe" not in names


def test_reality_generator_excludes_repo_local_uv_cache(tmp_path):
    (tmp_path / "source.py").write_text(
        "class IncludedProjectSource:\n    pass\n",
        encoding="utf-8",
    )
    uv_cache = tmp_path / ".uv-cache" / "archive-v0" / "dependency"
    uv_cache.mkdir(parents=True)
    (uv_cache / "cached_source.py").write_text(
        "class IgnoredUVCacheDependency:\n    pass\n",
        encoding="utf-8",
    )

    generated = RealityDAGGenerator(str(tmp_path), "UV cache exclusion test").generate()
    names = {node.name for node in generated.nodes.values()}

    assert "IncludedProjectSource" in names
    assert "IgnoredUVCacheDependency" not in names


def test_reality_generator_excludes_reproducibility_noise_directories(tmp_path):
    (tmp_path / "source.py").write_text(
        "class IncludedSource:\n    pass\n",
        encoding="utf-8",
    )
    for ignored_directory in (
        "dist",
        "build",
        "node_modules",
        ".pytest_cache",
        "package.egg-info",
    ):
        ignored_path = tmp_path / ignored_directory
        ignored_path.mkdir()
        (ignored_path / "duplicate.py").write_text(
            "class IgnoredBuildDuplicate:\n    pass\n",
            encoding="utf-8",
        )

    before = RealityDAGGenerator(str(tmp_path), "Noise exclusion test").generate()
    (tmp_path / "dist" / "second.py").write_text(
        "class AnotherIgnoredDuplicate:\n    pass\n",
        encoding="utf-8",
    )
    after = RealityDAGGenerator(str(tmp_path), "Noise exclusion test").generate()

    assert before.nodes == after.nodes
    assert before.edges == after.edges
    assert "IgnoredBuildDuplicate" not in {node.name for node in after.nodes.values()}


def test_reality_generator_parses_project_source_without_native_crash():
    project_root = Path(__file__).resolve().parents[1]
    command = (
        "from aio_agentic_sdlc.reality_dag_generator import RealityDAGGenerator; "
        f"RealityDAGGenerator({str(project_root / 'src')!r}, 'Self scan').generate()"
    )

    completed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_reality_generator_agent_guid_extraction():
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = os.path.join(tmpdir, ".agents", "agents")
        os.makedirs(agents_dir, exist_ok=True)
        agent_content = """---
name: ArchitectAgent
type: agent
description: An agent that designs architecture.
metadata:
  node_id: 2e8a1562-7e77-4402-992f-f461e8c7161f
---
# Some body
"""
        with open(os.path.join(agents_dir, "architect.md"), "w", encoding="utf-8") as f:
            f.write(agent_content)

        generator = RealityDAGGenerator(root_dir=tmpdir, system_name="TestSystem")
        dag = generator.generate()

        node_ids = {n.id: n for n in dag.nodes.values()}

        expected_uuid = "2e8a1562-7e77-4402-992f-f461e8c7161f"
        assert expected_uuid in node_ids
        assert node_ids[expected_uuid].type == NodeType.AGENT
        assert node_ids[expected_uuid].name == "ArchitectAgent"


def test_reality_generator_agent_numeric_guid_extraction():
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_dir = os.path.join(tmpdir, ".agents", "agents")
        os.makedirs(agents_dir, exist_ok=True)
        agent_content = """---
name: ArchitectAgent
type: agent
description: An agent that designs architecture.
metadata:
  node_id: 123456
---
# Some body
"""
        with open(os.path.join(agents_dir, "architect.md"), "w", encoding="utf-8") as f:
            f.write(agent_content)

        generator = RealityDAGGenerator(root_dir=tmpdir, system_name="TestSystem")
        dag = generator.generate()

        node_ids = {n.id: n for n in dag.nodes.values()}

        # 123456 is not a valid UUID, so it should be hashed by uuid5
        import uuid

        expected_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "123456"))
        assert expected_uuid in node_ids
        assert node_ids[expected_uuid].type == NodeType.AGENT
        assert node_ids[expected_uuid].name == "ArchitectAgent"
