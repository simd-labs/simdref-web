"""Static-content check for the shipped index.html.

Replaces core's old ``test_web_export_includes_category_and_kind_panels``
(dropped in the split: it asserted these ids in HTML that ``export_web``
used to template per catalog; ``web/index.html`` is now a static file
with no export step, so the check moves here as a plain string test.
"""

from __future__ import annotations

from pathlib import Path

INDEX_HTML = Path(__file__).parent.parent / "web" / "index.html"

REQUIRED_IDS = (
    "kind-bar",
    "isa-intel",
    "isa-arm32",
    "isa-arm64",
    "isa-riscv",
)


def test_index_html_has_kind_and_isa_panels():
    html = INDEX_HTML.read_text()
    for element_id in REQUIRED_IDS:
        assert f'id="{element_id}"' in html, f"missing #{element_id} in {INDEX_HTML}"

def test_index_html_has_no_category_filter():
    # A1: the Category filter can never match (no entry carries `category`),
    # so the panel, toggle and summary are gone from the shipped HTML.
    html = INDEX_HTML.read_text()
    for element_id in ("category-toggle", "category-panel", "category-chips"):
        assert f'id="{element_id}"' not in html, f"#{element_id} still in {INDEX_HTML}"
