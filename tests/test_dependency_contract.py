from pathlib import Path

import tomllib
from packaging.requirements import Requirement


def test_mcp_dependency_targets_the_reviewed_v2_api():
    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = {
        Requirement(value).name: Requirement(value)
        for value in project["project"]["dependencies"]
    }

    assert str(dependencies["mcp"].specifier) == "<3,>=2.0.0"
    locked = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    mcp_packages = [
        package for package in locked["package"] if package["name"] == "mcp"
    ]
    assert [package["version"] for package in mcp_packages] == ["2.0.0"]
