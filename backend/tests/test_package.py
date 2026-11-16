import tomllib
from pathlib import Path

import agentgymnasium


def test_package_importable():
    project = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8"))
    assert agentgymnasium.__version__ == project["project"]["version"]
