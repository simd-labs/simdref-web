"""FIXUI web checks: per-row perf source labels and narrow-width layout.

Defect 2 (web): every perf row keeps a compact source label; the group
footer citations stay. Driven through Node like the B5 check.

Defect 3: at 800-1100 px the perf table scrolls inside its own container
and the page keeps no horizontal overflow. The check is a plain string
test on style.css, following test_ui_parity.py.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
HARNESS = Path(__file__).parent / "web_assets" / "run_fixui_check.mjs"
STYLE_CSS = Path(__file__).parent.parent / "web" / "style.css"


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_fixui_perf_rows_keep_source_labels() -> None:
    assert NODE is not None  # narrow for type-checker
    result = subprocess.run(
        [NODE, str(HARNESS)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0, (
        f"app.js FIXUI check failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_kind_bar_wraps_before_overflow() -> None:
    css = STYLE_CSS.read_text()
    base = re.search(r"^\.kind-bar\s*\{([^}]*)\}", css, re.MULTILINE)
    assert base, "missing base .kind-bar rule"
    assert "flex-wrap: wrap" in base.group(1)


def test_category_select_caps_its_width() -> None:
    css = STYLE_CSS.read_text()
    base = re.search(r"^\.cat-filter\s*\{([^}]*)\}", css, re.MULTILINE)
    assert base, "missing base .cat-filter rule"
    assert "max-width: 100%" in base.group(1)


def test_detail_tables_scroll_below_1100px() -> None:
    css = STYLE_CSS.read_text()
    media = re.search(r"@media \(max-width: 1100px\)\s*\{([^@]*)\}", css)
    assert media, "missing max-width 1100px media block"
    rule = re.search(r"#detail table\s*\{([^}]*)\}", media.group(1))
    assert rule, "missing #detail table rule in the 1100px block"
    assert "overflow-x: auto" in rule.group(1)
