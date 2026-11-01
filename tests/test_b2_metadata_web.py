"""B2 web surface: metadata panel fields and the category facet.

Driven through Node like the search-index check: web/app.js is loaded
into a vm sandbox and renderIntrinsicDetail, renderInstructionDetail,
the operand table, decodeIntrinsics and the category facet are exercised
with the fixture records of simdref/tests/fixtures/b2/metadata_records.json.
Skips silently when node is not on PATH.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
HARNESS = Path(__file__).parent / "web_assets" / "run_b2_metadata_check.mjs"


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_metadata_panel_and_category_facet() -> None:
    assert NODE is not None  # narrow for type-checker
    result = subprocess.run(
        [NODE, str(HARNESS)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0, (
        f"app.js B2 metadata check failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
