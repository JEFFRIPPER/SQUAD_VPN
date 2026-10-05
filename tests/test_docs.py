"""The version is spelled out in several files; none of them may lag behind."""

import re
import tomllib
from pathlib import Path

import squad_vpn

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_the_same_everywhere():
    version = squad_vpn.__version__
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == version
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"**Версия {version}.**" in readme
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## (\S+)", changelog, re.M)
    assert first and first.group(1) == version
