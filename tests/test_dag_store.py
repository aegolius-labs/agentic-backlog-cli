import os
from datetime import datetime, timezone

import pytest
from click.testing import CliRunner

from aio_agentic_sdlc.dag_cli import cli
from aio_agentic_sdlc.dag_manager import DAGManager
from aio_agentic_sdlc.dag_models import Metadata, Node, NodeType
from aio_agentic_sdlc.dag_store import mutate_dag_file
from aio_agentic_sdlc.intent_migration import LegacyIntentMigrator
from aio_agentic_sdlc.reality_dag_generator import RealityDAGGenerator
from aio_agentic_sdlc.workspace import INTENTION_DAG_FILE

NODE_ID = "00000000-0000-0000-0000-0000000000a1"


def _dag(path, *, description="Preserved intent."):
    path.parent.mkdir(parents=True, exist_ok=True)
    manager = DAGManager(
        Metadata(name="Guard test", version="1.0"),
        [
            Node(
                id=NODE_ID,
                type=NodeType.COMPONENT,
                name="Guarded node",
                description=description,
            )
        ],
        [],
    )
    manager.save(str(path))
    return path


def _symlink(link, target):
    try:
        os.symlink(target, link)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")


def test_structural_mutation_rejects_symlinked_dag_without_external_write(tmp_path):
    external = _dag(tmp_path / "external.yaml", description="External state.")
    link = tmp_path / "linked.yaml"
    _symlink(link, external)
    before = external.read_bytes()

    with pytest.raises(ValueError, match="regular file"):
        mutate_dag_file(
            link,
            lambda manager: manager.update_node(
                NODE_ID,
                description="Escaped mutation.",
            ),
        )

    assert external.read_bytes() == before


def test_structural_mutation_rejects_leaf_swap_before_save(tmp_path):
    dag_path = _dag(tmp_path / "canonical.yaml")
    external = _dag(tmp_path / "external.yaml", description="External state.")
    external_before = external.read_bytes()

    def swap_leaf(manager):
        dag_path.unlink()
        _symlink(dag_path, external)
        manager.update_node(NODE_ID, description="Escaped mutation.")

    with pytest.raises(ValueError, match="regular file"):
        mutate_dag_file(dag_path, swap_leaf)

    assert external.read_bytes() == external_before


def test_intent_migration_rejects_leaf_swap_without_external_write(tmp_path):
    dag_path = _dag(tmp_path / INTENTION_DAG_FILE)
    migrator = LegacyIntentMigrator(tmp_path)
    plan = migrator.plan(
        recorded_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        actor="sdlc_cartographer",
        generator_version="aio-agentic-sdlc/test",
    )
    external = _dag(tmp_path / "external.yaml", description="External state.")
    external_before = external.read_bytes()
    dag_path.unlink()
    _symlink(dag_path, external)

    with pytest.raises(ValueError, match="regular file"):
        migrator.apply(plan)

    assert external.read_bytes() == external_before


def test_reality_generation_rejects_leaf_swap_without_external_write(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "module.py").write_text("class Included:\n    pass\n", encoding="utf-8")
    output = _dag(tmp_path / "reality.yaml")
    external = _dag(tmp_path / "external.yaml", description="External state.")
    external_before = external.read_bytes()
    original_generate = RealityDAGGenerator.generate

    def swap_then_generate(generator):
        generated = original_generate(generator)
        output.unlink()
        _symlink(output, external)
        return generated

    monkeypatch.setattr(
        "aio_agentic_sdlc.dag_cli.RealityDAGGenerator.generate",
        swap_then_generate,
    )

    result = CliRunner().invoke(
        cli,
        [
            "generate-reality",
            "--dir",
            str(source),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 1
    assert "regular file" in result.output
    assert external.read_bytes() == external_before
