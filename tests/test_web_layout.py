"""Browser tests for the viewport-height layout fix.

On origin/main `.layout` is `height: calc(100vh - 90px)` while the header,
the search bar and the kind bar take 142px, so the results list, the
detail panel and the page run past the window. `#annotate-view` carries
the same stale offset (`calc(100vh - 56px)`). The fit tests fail there;
the mobile test guards the page-scroll reset that the fix must keep.
"""

from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api")

_FIT_JS = """() => {
    const rows = Array.from(document.querySelectorAll('#results .result'));
    return {
        cardBottom: rows.length
            ? Math.max(...rows.map(r => r.getBoundingClientRect().bottom)) : 0,
        detailBottom: document.querySelector('#detail').getBoundingClientRect().bottom,
        scrollH: document.scrollingElement.scrollHeight,
        innerH: window.innerHeight,
    };
}"""

_ANN_JS = """() => ({
    bottom: document.querySelector('#annotate-view').getBoundingClientRect().bottom,
    scrollH: document.scrollingElement.scrollHeight,
    innerH: window.innerHeight,
})"""

# Clone rows like the M1 touch test: the fixture's 'vaddps' rows fit one
# screen, so the document needs padding to prove the page scroll.
_MOBILE_PAD_JS = """() => {
    const list = document.querySelector('#results');
    const rows = Array.from(list.children);
    for (let i = 0; i < 12; i++)
        rows.forEach(r => list.appendChild(r.cloneNode(true)));
}"""


def _search_vaddps(page, url):
    page.goto(url)
    # Phase 2 repaints the page and resets the list scroll; measure after it.
    page.wait_for_function(
        "() => document.body.dataset.phase2 === 'done'", timeout=60_000, polling=100
    )
    page.locator("#query").fill("vaddps")
    page.wait_for_function("document.querySelectorAll('#results .result').length > 0", polling=100)
    page.wait_for_timeout(200)


def _scroll_results_to_end(page):
    page.evaluate("document.querySelector('#results').scrollTop = 1e9")
    page.wait_for_timeout(300)


@pytest.mark.parametrize(("width", "height"), [(1280, 720), (1440, 900)])
def test_results_and_detail_fit_the_window(browser, page_url, width, height):
    """Scrolled to the last card, the card and the detail panel end at or
    above the window bottom and the document does not scroll."""
    page = browser.new_page(viewport={"width": width, "height": height})
    try:
        _search_vaddps(page, page_url)
        _scroll_results_to_end(page)
        m = page.evaluate(_FIT_JS)
        assert m["cardBottom"] <= m["innerH"] + 1, m
        assert m["scrollH"] == m["innerH"], m
        page.evaluate("document.querySelector('#results .result').click()")
        page.wait_for_function(
            "!!document.querySelector('#detail .detail-head')", timeout=15_000, polling=100
        )
        m = page.evaluate(_FIT_JS)
        assert m["detailBottom"] <= m["innerH"] + 1, m
        assert m["scrollH"] == m["innerH"], m
    finally:
        page.close()


@pytest.mark.parametrize(("width", "height"), [(1280, 720), (1440, 900)])
def test_results_fit_with_isa_panel_open(browser, page_url, width, height):
    """The open ISA panel takes its own height and the results list
    shrinks by that much; nothing runs past the window."""
    page = browser.new_page(viewport={"width": width, "height": height})
    try:
        _search_vaddps(page, page_url)
        page.evaluate("document.querySelector('#isa-toggle').click()")
        page.wait_for_function(
            "!document.querySelector('#isa-panel').classList.contains('hidden')", polling=100
        )
        page.wait_for_timeout(200)
        # The panel shrinks the list, so its end moves; re-scroll to it.
        _scroll_results_to_end(page)
        m = page.evaluate(_FIT_JS)
        assert m["cardBottom"] <= m["innerH"] + 1, m
        assert m["scrollH"] == m["innerH"], m
    finally:
        page.close()


@pytest.mark.parametrize(("width", "height"), [(1280, 720), (1440, 900)])
def test_annotate_view_fits_the_window(browser, page_url, width, height):
    """The Annotate view fills the window: its bottom lands on the window
    bottom and the document does not scroll."""
    page = browser.new_page(viewport={"width": width, "height": height})
    try:
        page.goto(page_url)
        page.wait_for_function(
            "() => document.body.dataset.phase2 === 'done'", timeout=60_000, polling=100
        )
        page.evaluate("document.querySelector('#tab-annotate').click()")
        page.wait_for_timeout(200)
        m = page.evaluate(_ANN_JS)
        assert m["bottom"] == pytest.approx(m["innerH"], abs=1), m
        assert m["scrollH"] == m["innerH"], m
    finally:
        page.close()


def test_mobile_layout_still_page_scrolls(browser, page_url):
    """At 390x844 the Search view scrolls the document; the desktop
    fixed-height clip must not come back on mobile."""
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        _search_vaddps(page, page_url)
        page.evaluate(_MOBILE_PAD_JS)
        page.wait_for_timeout(200)
        m = page.evaluate(
            "() => ({scrollH: document.scrollingElement.scrollHeight, innerH: window.innerHeight})"
        )
        assert m["scrollH"] > m["innerH"] + 100, m
    finally:
        page.close()
