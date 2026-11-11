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


# FIXUI2 defect 2 (SHOT3 shot-19): at 390 px a wide perf table clipped its
# UOPS column. Every perf table on the detail card must scroll inside its
# own box at any width up to 1100 px; the page itself keeps scrollWidth
# equal to clientWidth.
_PERF_ROWS = [
    {
        "uarch": "SKX",
        "source": "uops.info",
        "sourceVersion": "2025-10-30",
        "citationUrl": "https://uops.info/table.html",
        "latency": "4",
        "tpLoop": "0.55",
        "uops": "2",
        "sourceKind": "measured",
        "latencyPairs": [{"value": "10", "start": "xmm1", "target": "xmm0"}],
    },
    {
        "uarch": "neoverse-v1",
        "family": "Arm",
        "source": "llvm-mca",
        "sourceVersion": "24.0.0",
        "citationUrl": "https://llvm.org/docs/CommandGuide/llvm-mca.html",
        "latency": "2",
        "tpLoop": "0.5",
        "uops": "1",
        "sourceKind": "modeled",
    },
    {
        "uarch": "ZEN4",
        "source": "amd-swopt",
        "sourceVersion": "1.00",
        "citationUrl": "https://docs.amd.com/v/u/en-US/58455_1.00",
        "latency": "3",
        "tpLoop": "0.5",
        "uops": "1",
        "sourceKind": "modeled",
    },
]

_RENDER_PERF_JS = """
(rows) => {
    document.getElementById("detail").innerHTML = renderMeasurements(rows);
}
"""

_BOX_JS = """
() => {
    const tables = [];
    for (const t of document.querySelectorAll("#detail table")) {
        const box = t.closest(".perf-scroll");
        tables.push({
            inBox: !!box,
            overflow: box ? getComputedStyle(box).overflowX : null,
        });
    }
    return {tables,
            docSW: document.documentElement.scrollWidth,
            docCW: document.documentElement.clientWidth};
}
"""


def test_perf_tables_scroll_inside_own_box_below_1100px(browser, page_url) -> None:
    for width in (390, 800):
        page = browser.new_page(viewport={"width": width, "height": 800})
        try:
            page.goto(page_url)
            # Phase 2 repaints the page on completion; inject after it.
            page.wait_for_function(
                "() => document.body.dataset.phase2 === 'done'", timeout=60_000, polling=100
            )
            page.evaluate(_RENDER_PERF_JS, _PERF_ROWS)
            m = page.evaluate(_BOX_JS)
            assert m["tables"], f"no perf tables rendered at {width}px"
            for t in m["tables"]:
                assert t["inBox"] and t["overflow"] in ("auto", "scroll"), (
                    f"perf table without its own scroll box at {width}px: {t}"
                )
            assert m["docSW"] == m["docCW"], f"page scrolls sideways at {width}px: {m}"
        finally:
            page.close()
