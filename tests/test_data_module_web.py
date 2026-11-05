"""The web data and identity modules import in node without a DOM, and the
chunk loader answers from a fixture chunk (see
tests/web_assets/run_data_module_check.mjs)."""

import shutil
import subprocess

import pytest

node = shutil.which("node")
pytestmark = pytest.mark.skipif(not node, reason="node not installed")


def test_data_module_imports_and_loads_fixture():
    res = subprocess.run(
        [node, "tests/web_assets/run_data_module_check.mjs"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr or res.stdout
