"""B5 web checks: perf group labels name the core's real vendor/family
(never a fixed Intel label), and the ISA filter honors an entry whose
only Arm sub-ISA is SME.

Fixture rows: aarch64/riscv measurement rows with an export family
label, plus legacy x86 codes. The SME filter check drives the FAMILY_SUB
config the export writes.

Driven through Node like the B4 check. Skips silently when node is not
on PATH.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
HARNESS = Path(__file__).parent / "web_assets" / "run_b5_check.mjs"


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_b5_web() -> None:
    assert NODE is not None  # narrow for type-checker
    result = subprocess.run(
        [NODE, str(HARNESS)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0, (
        f"app.js B5 check failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
