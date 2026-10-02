"""Regression tests for the web fixes F1-F3.

F1/F3 fail on origin/main and pass after the fix; F2 uses the existing
row-height parity test in test_ui_parity.py plus the rendered-row
assertion here.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def _read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_f1_count_syncs_after_rows_render():
    # F1: syncResultsCount() must run after renderVisibleResults(), or the
    # count reads "Showing 0 of N" until the next render tick.
    text = _read("app.js")
    render_idx = text.index("renderVisibleResults(true);")
    sync_idx = text.index("syncResultsCount(query);")
    assert render_idx < sync_idx, (
        "syncResultsCount(query) runs before renderVisibleResults(true): "
        "the count shows 'Showing 0 of N' right after a query (F1)"
    )


def test_f2_row_height_holds_three_lines():
    # F2: the row holds title + perf + summary plus badges; at the old 56px
    # the perf line was cut in half. 68px fits all three lines.
    js = re.search(r"ROW_HEIGHT_PX\s*=\s*(\d+)", _read("app.js"))
    css = re.search(r"\.result\s*\{[^}]*?height:\s*(\d+)px", _read("style.css"), re.DOTALL)
    assert js and css
    assert js.group(1) == css.group(1), "ROW_HEIGHT_PX must match .result height"
    assert int(js.group(1)) >= 68, f"row height {js.group(1)}px clips the perf line (F2)"


def test_f3_mobile_horizontal_overflow_clamped():
    # F3: at 390px the page reported scrollWidth 473. The media query must
    # clamp the layout and hide non-essential header chrome.
    css = _read("style.css")
    mobile = css[css.index("@media (max-width: 768px)"):]
    assert "overflow-x: hidden" in mobile, "missing the overflow clamp (F3)"
    assert "flex-wrap: wrap" in mobile, "header does not wrap on mobile (F3)"
    assert re.search(r"@media \(max-width: 480px\)[^}]*a\.icon-btn", css.replace("\n", " ")), (
        "GitHub/PyPI header icons must hide under 480px (F3)"
    )
