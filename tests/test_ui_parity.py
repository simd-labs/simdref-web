"""Drift guards ported from core's test_preset_persistence.py / test_ui_labels_parity.py.

These were pure text checks against the templated app.js/index.html and had no
`simdref` import, so the split moves them here unchanged rather than dropping them.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def _read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_preset_precedence_url_beats_localstorage_beats_intel():
    text = _read("app.js")
    url_idx = text.index('params.get("preset")')
    storage_idx = text.index('localStorage.getItem("simdref-last-preset")')
    fallback_idx = text.index('ARCH_PRESETS["intel"] ? "intel"')
    assert url_idx < storage_idx < fallback_idx, (
        "preset precedence must be: URL param > localStorage > intel"
    )


def test_preset_click_persists_to_localstorage():
    assert 'localStorage.setItem("simdref-last-preset"' in _read("app.js")


def test_result_row_height_constant_matches_css():
    css_match = re.search(r"\.result\s*\{[^}]*?height:\s*(\d+)px", _read("style.css"), re.DOTALL)
    js_match = re.search(r"ROW_HEIGHT_PX\s*=\s*(\d+)", _read("app.js"))
    assert css_match and js_match
    assert css_match.group(1) == js_match.group(1), (
        f"CSS row height {css_match.group(1)}px != JS ROW_HEIGHT_PX {js_match.group(1)}"
    )


def test_no_drifted_kind_bar_label():
    assert "> asm / instructions<" not in _read("index.html")


def test_modeled_toggle_names_arm_riscv_not_intel():
    # All x86 rows are measured; modeled data is ARM/RISC-V (llvm-mca).
    html = _read("index.html")
    assert "modeled (Intel)" not in html
    assert "Intel-modeled" not in html
    assert "modeled (ARM/RISC-V)" in html


def test_web_cpi_uses_exported_value_not_fallback():
    # perf.perf_row_values in Python is the only place that picks CPI;
    # app.js must display the exported tpLoop, never recompute it.
    text = _read("app.js")
    m = re.search(r"function _cpiValue\(row\) \{(?P<body>.*?)\n\}", text, re.DOTALL)
    assert m, "_cpiValue missing from app.js"
    body = m.group("body")
    assert "row.tpLoop" in body
    assert "tpUnrolled" not in body
    assert "tpPorts" not in body
