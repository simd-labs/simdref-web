"""B3 web surface: SDM table sections in the instruction detail view.

Driven through Node like the metadata check: web/app.js is loaded into a
vm sandbox and renderInstructionDetail is exercised with a fixture record
that holds the Opcode & Modes, Operand Encoding and exception reference
sections. Skips silently when node is not on PATH.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
HARNESS = Path(__file__).parent / "web_assets" / "run_b3_sdm_fields_check.mjs"


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_sdm_fields_in_web_detail() -> None:
    assert NODE is not None  # narrow for type-checker
    result = subprocess.run(
        [NODE, str(HARNESS)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0, (
        f"app.js B3 SDM fields check failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
