import yaml

from aio_agentic_sdlc.cli import migrate_ids_cmd
from aio_agentic_sdlc.workspace import INTENTION_DAG_FILE, REALITY_DAG_FILE


class DummyArgs:
    pass


def test_migrate_ids_maintains_cross_file_consistency(tmpdir, monkeypatch):
    monkeypatch.chdir(tmpdir)

    intention_data = {
        "nodes": [{"id": "shared-node-1", "type": "module", "name": "Shared"}],
        "edges": [],
    }
    reality_data = {
        "nodes": [{"id": "shared-node-1", "type": "module", "name": "Shared"}],
        "edges": [],
    }

    (tmpdir / ".aio-agentic-sdlc").ensure(dir=True)
    with open(INTENTION_DAG_FILE, "w") as f:
        yaml.dump(intention_data, f)
    with open(REALITY_DAG_FILE, "w") as f:
        yaml.dump(reality_data, f)

    migrate_ids_cmd(DummyArgs())

    with open(INTENTION_DAG_FILE, "r") as f:
        int_data = yaml.safe_load(f)
    with open(REALITY_DAG_FILE, "r") as f:
        real_data = yaml.safe_load(f)

    int_id = int_data["nodes"][0]["id"]
    real_id = real_data["nodes"][0]["id"]

    assert int_id == real_id, f"IDs diverged! Intention: {int_id}, Reality: {real_id}"
