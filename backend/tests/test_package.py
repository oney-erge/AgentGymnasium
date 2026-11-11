import tomllib
from pathlib import Path

import agentgymnasium


def test_package_importable():
    # The version the package reports is the one it is released as (pyproject.toml).
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert agentgymnasium.__version__ == expected
