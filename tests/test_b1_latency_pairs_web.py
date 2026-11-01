"""B1 web surface: latency per operand pair in the detail view.

Driven through Node like the search-index check: web/app.js is loaded
into a vm sandbox and renderMeasurements is exercised with the fixture
measurement rows of tests/fixtures/b1/latency_pairs.json (see the simdref
repo). Skips silently when node is not on PATH.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
HARNESS = Path(__file__).parent / "web_assets" / "run_latency_pairs_check.mjs"


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_latency_pairs_render_in_detail_view() -> None:
    assert NODE is not None  # narrow for type-checker
    result = subprocess.run(
        [NODE, str(HARNESS)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0, (
        f"app.js latency-pairs check failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
