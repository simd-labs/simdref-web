"""B4 web parity: the detail-card CPI summary uses the same aggregate as
the search list (lowest over cores), the modeled perf rows show their
provenance (source name, source_version and citationUrl) as a link under
the perf table, and the list LAT/CPI chips name the rule in a tooltip.

Driven through Node like the B3 check. Skips silently when node is not on
PATH.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
HARNESS = Path(__file__).parent / "web_assets" / "run_b4_parity_check.mjs"


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_b4_parity_in_web() -> None:
    assert NODE is not None  # narrow for type-checker
    result = subprocess.run(
        [NODE, str(HARNESS)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0, (
        f"app.js B4 parity check failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
