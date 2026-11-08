"""Hover tests for the Annotate tab's record popover.

Hovering an annotated output line shows the simdref record of the form
the line matched: the form key (a deep link), the guarded summary, and
the per-core measurement table (latency, CPI, ports, uops) the detail
view already renders. Unknown lines (``# ??``) carry no record and
show nothing. The .sa payload (Copy .sa, Download .sa) stays
byte-identical to the base render: it is the text of ``#ann-output``,
and the hover spans add no text.

Skips when Playwright or chromium is missing, like the rest of the
browser suite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from conftest import SITE_DATA, _free_port, _populate_site, _serve  # noqa: E402

SAMPLE = "addq %rax, %rbx\nvaddps %ymm2, %ymm1, %ymm0\nfoobarq %rax, %rbx"

# outputAsText() for SAMPLE at the base commit 95455b5, against a real
# simdref export: the .sa payload the hover change must not alter.
BASE_SA = (
    "addq %rax, %rbx   # Add 64-bit integer operands. | lat=8.33c "
    "cpi=0.83 [avg of 36 archs, measured]\n"
    "vaddps %ymm2, %ymm1, %ymm0   # Add Packed Single Precision "
    "Floating-Point Values. | lat=11.19c cpi=0.65 [avg of 26 archs, "
    "measured]\n"
    "foobarq %rax, %rbx   # ??"
)

HAS_DETAIL = (SITE_DATA / "detail-chunks" / "ADD.json").exists()


def _record_for(key: str) -> dict | None:
    """The served export's detail record for a matched form key."""
    mnemonic = key.split(":", 1)[1].split(" ")[0].upper()
    chunk = SITE_DATA / "detail-chunks" / f"{mnemonic}.json"
    if not chunk.exists():
        return None
    return json.loads(chunk.read_text()).get(key)


@pytest.fixture()
def annotate_page(browser, tmp_path):
    """A page with the sample document annotated; identity unavailable
    (the harness serves no wasm, so the base render is final)."""
    site = tmp_path / "site"
    _populate_site(site)
    port = _free_port()
    with _serve(site, port):
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        try:
            page.goto(f"http://127.0.0.1:{port}/")
            page.wait_for_function("() => document.body.dataset.phase2 === 'done'", timeout=60_000)
            page.evaluate("() => { document.body.dataset.tab = 'annotate'; }")
            page.evaluate(
                "(doc) => { document.querySelector('#ann-input').value = doc;"
                " document.querySelector('#ann-isa').value = 'x86'; runAnnotate(); }",
                SAMPLE,
            )
            page.wait_for_function(
                "() => document.querySelector('#ann-status').textContent.includes('annotated')",
                timeout=30_000,
            )
            page.wait_for_function(
                "() => document.querySelector('#ann-status').textContent.includes('unavailable')",
                timeout=60_000,
            )
            yield page
        finally:
            page.close()


def _hover_first_line(page):
    line = page.locator("#ann-output .ann-line").first
    line.hover()
    page.wait_for_function("() => !document.querySelector('#ann-hover-pop').hidden", timeout=5_000)
    return line


def test_hover_shows_the_record(annotate_page):
    page = annotate_page
    out = page.locator("#ann-output")
    # Only the two known lines are hoverable; the unknown line is not wrapped.
    assert out.locator(".ann-line").count() == 2
    _hover_first_line(page)

    key = page.evaluate("() => _annHoverRecs[0].entry.key")
    assert key.startswith("x86:add")
    pop = page.locator("#ann-hover-pop")
    text = pop.text_content()
    assert key in text
    # The key is a deep link: '#' + the URL-encoded entry key.
    href = pop.locator(".ann-hover-key a").get_attribute("href")
    assert href == "#" + page.evaluate("(k) => encodeURIComponent(k)", key)

    # The summary the annotation comment shows up top, minus the perf tail.
    line_text = out.locator(".ann-line").first.text_content()
    summary = line_text.split("# ", 1)[1].split(" | lat=")[0]
    assert summary and summary in text

    # The per-core table: one row per measurement, LAT column intact.
    lats = page.evaluate(
        "() => [...document.querySelectorAll('#ann-hover-pop table tr')]"
        ".slice(1).map(tr => tr.children[2].textContent)"
    )
    rec = _record_for(key)
    if rec:
        # Mirror renderTable's cell for a missing/null latency ("-" there).
        expected = [
            str(m["latency"]) if m.get("latency") is not None else "-" for m in rec["measurements"]
        ]
        assert lats == expected
        assert any(v for v in expected)  # the record carries latency data
    else:
        assert lats == []  # no detail chunks served: no table rows


def test_hover_on_unknown_line_shows_nothing(annotate_page):
    page = annotate_page
    out = page.locator("#ann-output")
    unknown = out.locator(".hl-unknown")
    assert unknown.count() == 1
    assert unknown.text_content() == "# ??"

    _hover_first_line(page)
    # The open popover floats over the following lines and intercepts the
    # pointer, so dispatch the mouseover instead of a real move.
    page.evaluate(
        "() => document.querySelector('#ann-output .hl-unknown')"
        ".dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))"
    )
    page.wait_for_timeout(200)
    assert page.evaluate("() => document.querySelector('#ann-hover-pop').hidden")


def test_copy_sa_payload_unchanged(annotate_page):
    page = annotate_page
    got = page.evaluate("() => outputAsText()")
    if HAS_DETAIL:
        assert got == BASE_SA
    else:  # committed fixture data: no measurements in the annotation
        lines = got.split("\n")
        assert len(lines) == 3
        assert lines[0].startswith("addq %rax, %rbx   # ")
        assert lines[2] == "foobarq %rax, %rbx   # ??"
