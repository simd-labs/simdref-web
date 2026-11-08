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


# 34 annotated lines push the last line to the bottom of an 800px viewport.
LONG_SAMPLE = "\n".join(["addq %rax, %rbx"] * 34)


@pytest.fixture()
def annotate_page_bottom(browser, tmp_path):
    """The long sample at 1280x800: the last annotated line sits at the
    bottom of the viewport, so a popover below it cannot fit."""
    site = tmp_path / "site"
    _populate_site(site)
    port = _free_port()
    with _serve(site, port):
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        try:
            page.goto(f"http://127.0.0.1:{port}/")
            page.wait_for_function("() => document.body.dataset.phase2 === 'done'", timeout=60_000)
            page.evaluate("() => { document.body.dataset.tab = 'annotate'; }")
            page.evaluate(
                "(doc) => { document.querySelector('#ann-input').value = doc;"
                " document.querySelector('#ann-isa').value = 'x86'; runAnnotate(); }",
                LONG_SAMPLE,
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


def test_hover_last_line_popover_stays_in_viewport(annotate_page_bottom):
    """Near the bottom of the viewport the popover opens above the line,
    caps at the viewport with overflow-y auto, and its last table row is
    fully visible once the box is scrolled to the bottom."""
    page = annotate_page_bottom
    if not HAS_DETAIL:
        pytest.skip("no detail data served: no table to cap")
    out = page.locator("#ann-output")
    n = out.locator(".ann-line").count()
    assert n == 34
    last = out.locator(".ann-line").nth(n - 1)
    # Scroll the output to the bottom. A large finite value: assigning
    # Infinity is converted to 0 by the WebIDL unsigned-long setter.
    page.evaluate("() => { document.querySelector('#ann-output').scrollTop = 100000; }")
    page.wait_for_timeout(200)
    line_box = last.bounding_box()
    # The sample is long enough that the last line sits at the pane
    # bottom, near the viewport bottom: opening below it cannot fit.
    assert line_box["y"] + line_box["height"] > 800 - 50

    last.hover()
    page.wait_for_function("() => !document.querySelector('#ann-hover-pop').hidden", timeout=5_000)
    page.wait_for_timeout(200)
    pop_box = page.evaluate(
        """() => {
          const r = document.querySelector('#ann-hover-pop').getBoundingClientRect();
          return {top: r.top, bottom: r.bottom, left: r.left,
                  right: r.right, height: r.height};
        }"""
    )
    # The box lies fully inside the 1280x800 viewport and opened above
    # the line (no room below).
    assert pop_box["top"] >= 0
    assert pop_box["bottom"] <= 800
    assert pop_box["left"] >= 0
    assert pop_box["right"] <= 1280
    assert pop_box["top"] < line_box["y"]
    # The cap is the viewport, not the old fixed 440px height.
    assert pop_box["height"] > 440

    # The table is longer than the box: scrolling to the bottom puts the
    # last row fully inside the box, not clipped mid-row.
    page.evaluate(
        "() => { const p = document.querySelector('#ann-hover-pop');"
        " p.scrollTop = p.scrollHeight; }"
    )
    page.wait_for_timeout(200)
    geom = page.evaluate(
        """() => {
          const pop = document.querySelector('#ann-hover-pop');
          const pr = pop.getBoundingClientRect();
          const rows = pop.querySelectorAll('table tr');
          const lr = rows[rows.length - 1].getBoundingClientRect();
          return {popTop: pr.top, popBottom: pr.bottom,
                  rowTop: lr.top, rowBottom: lr.bottom};
        }"""
    )
    assert geom["rowTop"] >= geom["popTop"] - 1
    assert geom["rowBottom"] <= geom["popBottom"] + 1
