"""Browser regression tests for the web fixes (F1-F3 plus R2 review round).

Behaviour tests against the live page; each fails on origin/main and passes
on HEAD. F1: count shows "0 of N"; F2: 56px rows clip the perf line; F3:
scrollWidth 473 at 390px. R2 items: hash deep link with empty query, tab
fallback, linked-intrinsics tab, doc links, perf-source summary, perf goto,
number-key guards.
"""

from __future__ import annotations

import os
import socket
import threading
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError, sync_playwright  # noqa: E402

import sys
sys.path.insert(0, str(Path(__file__).parent))
from test_web_e2e import _populate_site  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass


@contextmanager
def _serve(directory: Path, port: int):
    handler = lambda *a, **k: _Quiet(*a, directory=str(directory), **k)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


@pytest.fixture(scope="module")
def browser():
    try:
        pw = sync_playwright().start()
    except Exception as exc:
        pytest.skip(f"playwright unavailable: {exc}")
    try:
        b = pw.chromium.launch(headless=True)
    except PlaywrightError as exc:
        pw.stop()
        pytest.skip(f"chromium not installed for playwright: {exc}")
    try:
        yield b
    finally:
        b.close()
        pw.stop()


@pytest.fixture()
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("web")
    _populate_site(out)
    port = _free_port()
    with _serve(out, port):
        yield out, f"http://127.0.0.1:{port}/"


def test_f1_count_updates_after_rows_render(browser, site):
    """F1: right after a query the count must agree with the rendered rows,
    never 'Showing 0 of N'."""
    _, url = site
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    try:
        page.goto(url)
        page.locator("#query").fill("_mm_add_ps")
        page.wait_for_function("document.querySelectorAll('#results .result').length > 0")
        rows = page.evaluate("document.querySelectorAll('#results .result').length")
        count = page.text_content("#results-count") or ""
        assert rows > 0
        assert " 0 of " not in f" {count} ", f"count ran before render: {count!r}"
        first = count.split()[0]
        assert first.isdigit() and int(first) > 0, count
    finally:
        page.close()


def test_f2_perf_line_inside_row_box(browser, site):
    """F2: a rendered row's perf line must sit inside its row box (the 56px
    row height cut it in half)."""
    _, url = site
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    try:
        page.goto(url)
        page.locator("#query").fill("_mm_add_ps")
        page.wait_for_function(
            "document.querySelectorAll('#results .result .result-perf').length > 0")
        clipped = page.evaluate(
            """Array.from(document.querySelectorAll('#results .result')).map(row => {
                const perf = row.querySelector('.result-perf');
                if (!perf) return null;
                const r = row.getBoundingClientRect(), p = perf.getBoundingClientRect();
                return (p.top < r.top - 0.5 || p.bottom > r.bottom + 0.5) ? row.dataset.key : null;
            }).filter(Boolean)"""
        )
        assert not clipped, f"perf line clipped in rows: {clipped}"
    finally:
        page.close()


def test_f3_no_horizontal_overflow_at_390(browser, site):
    """F3: at a 390px viewport the document must not scroll sideways."""
    _, url = site
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(url)
        page.wait_for_function("() => document.getElementById('query')")
        page.wait_for_function("() => document.getElementById('results-count').textContent.length > 0")
        sw = page.evaluate("document.documentElement.scrollWidth")
        assert sw <= 390, f"document scrollWidth {sw}px at a 390px viewport"
    finally:
        page.close()


def test_empty_query_resolves_hash_selection(browser, site):
    """R2-2: empty query plus a #key hash must still open that entry
    (bookmarkable links) even though the landing list is gone."""
    _, url = site
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    try:
        page.goto(url + "#x86%3Aaddps%20(xmm%2C%20xmm)")
        page.wait_for_function(
            "() => document.querySelector('#detail .detail-head')",
            timeout=15_000,
        )
        text = page.text_content("#detail") or ""
        assert "ADDPS" in text.upper(), text[:200]
    finally:
        page.close()


def _goto_addps_detail(page, url):
    page.goto(url)
    # '(xmm, xmm)' form; the plain 'addps' query ranks the (xmm, m128)
    # form first, which carries no linked intrinsics.
    page.locator("#query").fill("addps (xmm, xmm)")
    page.wait_for_function(
        "document.querySelectorAll('#results .result').length > 0")
    page.evaluate("document.querySelector('#results .result').click()")
    page.wait_for_function(
        "() => document.querySelector('#detail .detail-head')", timeout=15_000)
    page.wait_for_function(
        "() => document.querySelector('#detail .detail-tabs')", timeout=15_000)


def _settled(page):
    """Wait until Phase-2 ingest is done and a detail with tabs is shown.

    During ingest the app re-renders per batch and the tab bar blinks out
    and back; one-shot evaluates can land in the gap. intrinsicsReady
    resolves only when every batch has been folded in (same approach as
    test_web_e2e._wait_intrinsics_loaded)."""
    page.wait_for_function("() => intrinsicsReady !== null", timeout=60_000)
    page.evaluate("() => intrinsicsReady")
    page.wait_for_function(
        "() => document.querySelectorAll('#detail .detail-tabs button').length === 4",
        timeout=15_000)


def _visible_sections(page):
    return page.evaluate(
        "Array.from(document.querySelectorAll('#detail section.section:not(.detail-hidden)'))"
        ".map(s => s.innerText)")


def _tab(page, label):
    page.evaluate(
        f"Array.from(document.querySelectorAll('#detail .detail-tabs button'))"
        f".find(b => /{label}/.test(b.textContent))?.click()")
    page.wait_for_function(
        f"""Array.from(document.querySelectorAll('#detail .detail-tabs button'))
            .find(b => /{label}/.test(b.textContent))
            ?.getAttribute('aria-selected') === 'true'""",
        timeout=10_000)


def test_linked_intrinsics_live_in_related_tab(browser, site):
    """R2-4: an instruction's linked-intrinsics section sits under the
    Related tab, not Semantics. Real data: ADDPS links _mm_add_ps."""
    _, url = site
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    try:
        _goto_addps_detail(page, url)
        from urllib.parse import unquote
        assert "x86:addps (xmm, xmm)" in unquote(page.evaluate("location.hash"))
        _settled(page)
        _tab(page, "Related")
        visible = _visible_sections(page)
        assert any("_mm_add_ps" in v for v in visible), visible
        _tab(page, "Semantics")
        visible = _visible_sections(page)
        assert not any("_mm_add_ps" in v for v in visible), visible
    finally:
        page.close()


def test_default_tab_falls_back_when_no_perf(browser, site):
    """R2-3: an entry with no measurements opens on a tab with content, not
    an empty Perf panel."""
    _, url = site
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    try:
        page.goto(url)
        page.evaluate("localStorage.removeItem('simdref-c3-tab')")
        # Hash navigation bypasses the kind filter: plain NEG has no
        # measurements in the export.
        page.goto(url + "#x86%3Aneg%20(r32%2C%20r32)")
        page.wait_for_function(
            "() => document.querySelector('#detail .detail-head')", timeout=20_000)
        _settled(page)
        # confirm this really is a no-perf entry
        n = page.evaluate("!!document.querySelector('#detail #perf-sec')")
        assert not n, "test subject unexpectedly has a perf section"
        assert len(_visible_sections(page)) >= 1, "default view renders zero visible sections"
        sel = page.evaluate(
            "Array.from(document.querySelectorAll('#detail .detail-tabs button'))"
            ".map(b => b.getAttribute('aria-selected')).join(',')")
        assert "true" in sel, sel
        perf_sel = page.evaluate(
            "Array.from(document.querySelectorAll('#detail .detail-tabs button'))"
            ".find(b => /Perf/.test(b.textContent))?.getAttribute('aria-selected')")
        assert perf_sel in ("false", None), perf_sel
    finally:
        page.close()


def _set_perf_kinds(page, kinds):
    page.evaluate(
        """kinds => {
            for (const cb of document.querySelectorAll("#kind-bar input[data-perf-kind]")) {
                const want = kinds.includes(cb.dataset.perfKind);
                if (cb.checked === want) continue;
                cb.checked = want;
                cb.dispatchEvent(new Event("change", {bubbles: true}));
            }
        }""",
        kinds,
    )


def test_perf_summary_obeys_source_filter(browser, site):
    """R2-6: the head perf summary filters through enabledPerfKinds, like
    renderMeasurements. ADDPS carries measured and modeled rows."""
    _, url = site
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    try:
        page.goto(url)
        _set_perf_kinds(page, ["measured", "modeled"])
        # page.locator().fill keeps the hash the app set; navigate afresh
        _goto_addps_detail(page, url)
        _settled(page)
        both = page.evaluate("document.querySelector('#detail .perf-line')?.innerText || ''")
        assert "Latency" in both, both
        _set_perf_kinds(page, ["measured"])
        _goto_addps_detail(page, url)
        meas = page.evaluate("document.querySelector('#detail .perf-line')?.innerText || ''")
        assert "Latency" in meas, meas
        _set_perf_kinds(page, ["modeled"])
        _goto_addps_detail(page, url)
        mod = page.evaluate("document.querySelector('#detail .perf-line')?.innerText || ''")
        assert (mod != meas) or (mod == ""), (meas, mod)
        _set_perf_kinds(page, [])
        _goto_addps_detail(page, url)
        assert page.evaluate("document.querySelector('#detail .perf-line')") is None
    finally:
        page.close()


def test_documentation_links_restored(browser, site):
    """R2-8: instruction detail keeps the Reference/uops.info links from
    metadata, exactly as origin/main rendered them. ADDPS has both."""
    _, url = site
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    try:
        _goto_addps_detail(page, url)
        _settled(page)
        head_links = page.evaluate(
            "Array.from(document.querySelectorAll('#detail .detail-head a.kv-link'))"
            ".map(a => a.textContent)")
        assert any("Reference" in t for t in head_links), head_links
        assert any("uops.info" in t for t in head_links), head_links
    finally:
        page.close()


def test_perf_goto_switches_tab_then_scrolls(browser, site):
    """R2-7: the perf summary control selects the Perf tab, then scrolls."""
    _, url = site
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    try:
        _goto_addps_detail(page, url)
        _settled(page)
        _tab(page, "Semantics")
        page.evaluate("""(() => {
            localStorage.setItem('simdref-perf-kinds', JSON.stringify(['measured','modeled']));
            const q = document.querySelector('#detail .perf-line');
            if (q) q.click();
        })()""")
        page.wait_for_function(
            "Array.from(document.querySelectorAll('#detail .detail-tabs button'))"
            ".find(b => /Perf/.test(b.textContent))?.getAttribute('aria-selected') === 'true'",
            timeout=10_000)
        assert page.evaluate(
            "document.getElementById('perf-sec')?.classList.contains('detail-hidden')") is False
    finally:
        page.close()


def test_number_keys_ignore_modifiers_and_inputs(browser, site):
    """R2-9: Ctrl/Alt/Meta+digit and typing into an input never switch tabs."""
    _, url = site
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    tab_sel = ("Array.from(document.querySelectorAll('#detail .detail-tabs button'))"
               ".map(b => b.getAttribute('aria-selected')).join(',')")
    try:
        _goto_addps_detail(page, url)
        _settled(page)
        page.evaluate("document.getElementById('detail').focus()")
        page.wait_for_timeout(100)
        sel0 = page.evaluate(tab_sel)
        assert "true" in sel0, sel0
        page.keyboard.down("Control")
        page.keyboard.press("1")
        page.keyboard.up("Control")
        page.wait_for_timeout(100)
        assert page.evaluate(tab_sel) == sel0
        page.keyboard.down("Alt")
        page.keyboard.press("2")
        page.keyboard.up("Alt")
        page.wait_for_timeout(100)
        assert page.evaluate(tab_sel) == sel0
        page.locator("#query").click()
        page.keyboard.press("2")
        page.wait_for_timeout(100)
        assert page.evaluate(tab_sel) == sel0
    finally:
        page.close()
