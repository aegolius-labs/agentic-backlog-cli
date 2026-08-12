from pathlib import Path

import tomllib
from packaging.requirements import Requirement


def test_mcp_dependency_excludes_the_unsupported_v2_api():
    project = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = {
        Requirement(value).name: Requirement(value)
        for value in project["project"]["dependencies"]
    }

    assert str(dependencies["mcp"].specifier) == "<2,>=1.28.0"
