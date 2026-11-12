"""Browser tests for the doc-section order in the detail pane.

simdref sorts every export JSON key for deterministic bytes, which made
the sections render alphabetically. The export writes them as
``[heading, text]`` pairs in doc page order, and the pane renders that
order. One Playwright test per shape, run on the committed fixture site
data whatever SIMDREF_WEB_SITE_DATA points at:

F1: a new-shape entry renders its instruction sections and its doc
    sections in the stored pair order.
F2: the old dict shape still renders, in its key order.

Skips when Playwright or its chromium browser are missing. The shared
server and browser fixtures live in conftest.py.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError, sync_playwright  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from conftest import FIXTURE_SITE_DATA, STATIC_FILES, _free_port, _serve  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent
NEW_SHAPE = Path(__file__).parent / "fixtures" / "section-order"

# The NVIDIA PTX ISA page order of the activemask section.
PAGE_ORDER = ["Syntax", "Description", "PTX ISA Notes", "Target ISA Notes", "Examples"]
# The CUDA guide doc-section order of a device intrinsic.
DOC_ORDER = ["Description", "Return", "Parameters"]
# The key order of the old-shape dict in the committed fixture.
OLD_ORDER = ["Syntax", "Description", "Examples", "PTX ISA Notes", "Target ISA Notes"]


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


def _site_url(tmp_path_factory, overlay: Path | None) -> str:
    out = tmp_path_factory.mktemp("section-order-web")
    shutil.copytree(FIXTURE_SITE_DATA, out, dirs_exist_ok=True)
    if overlay is not None:
        for chunk in ("detail-chunks", "intrinsic-chunks"):
            shutil.copytree(overlay / chunk, out / chunk, dirs_exist_ok=True)
    for name in STATIC_FILES:
        shutil.copy(REPO_ROOT / "web" / name, out / name)
    port = _free_port()
    with _serve(out, port):
        yield f"http://127.0.0.1:{port}/"


@pytest.fixture(scope="module")
def new_shape_url(tmp_path_factory):
    yield from _site_url(tmp_path_factory, NEW_SHAPE)


@pytest.fixture(scope="module")
def old_shape_url(tmp_path_factory):
    yield from _site_url(tmp_path_factory, None)


def _open(page, url):
    page.goto(url)
    page.wait_for_function(
        "() => document.body.dataset.phase2 === 'done'", timeout=60_000, polling=100
    )


def _enable_families(page, families):
    """Switch the named ISA families on: the CUDA preset reaches the
    preset-only CUDA and PTX families, the chips cover the rest."""
    page.locator("#isa-toggle").click()
    page.wait_for_selector("#isa-panel:not(.hidden)", timeout=10_000)
    wanted = list(families)
    if "CUDA" in wanted or "PTX" in wanted:
        page.locator("#isa-cuda").click()
        page.wait_for_timeout(200)
        wanted = [f for f in wanted if f not in ("CUDA", "PTX")]
    for family in wanted:
        # The checkbox hides inside its label, so click it through the DOM.
        cb = page.locator(f'#isa-families input[data-family="{family}"]')
        if not cb.is_checked():
            cb.evaluate("el => el.click()")
    page.wait_for_timeout(300)


def _open_detail(page, query, key, title):
    page.locator("#query").fill(query)
    page.wait_for_function(
        "key => Array.from(document.querySelectorAll('#results .result'))"
        ".some(r => r.dataset.key === key)",
        arg=key,
        timeout=15_000,
        polling=100,
    )
    page.evaluate(
        "key => Array.from(document.querySelectorAll('#results .result'))"
        ".find(r => r.dataset.key === key)?.click()",
        key,
    )
    page.wait_for_function(
        "title => (document.querySelector('#detail h2')?.textContent || '').includes(title)",
        arg=title,
        timeout=15_000,
        polling=100,
    )
    page.wait_for_function(
        "() => document.querySelector('#detail .kv-compact')", timeout=15_000, polling=100
    )


def _section_summaries(page, heading):
    """Section headings of the detail block whose h3 text equals *heading*."""
    return page.evaluate(
        """heading => {
          const h3s = [...document.querySelectorAll('#detail section.section h3')];
          const h3 = h3s.find(e => e.textContent.trim() === heading);
          if (!h3) return [];
          return [...h3.parentElement.querySelectorAll('.desc-section summary')]
            .map(e => e.textContent.trim());
        }""",
        heading,
    )


def test_new_shape_sections_render_in_stored_order(browser, new_shape_url):
    """A new-shape entry renders its instruction sections and its doc
    sections in the pair order the export wrote."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, new_shape_url)
        _enable_families(page, ["CUDA"])
        _open_detail(page, "activemask.b32", "ptx:activemask.b32", "activemask.b32")
        assert _section_summaries(page, "Instruction Semantics") == PAGE_ORDER
        _open_detail(page, "__activemask", "__activemask", "__activemask")
        summaries = _section_summaries(page, "cuda guide documentation")
        assert summaries == DOC_ORDER
    finally:
        page.close()


def test_old_shape_sections_still_render(browser, old_shape_url):
    """The committed old-shape fixture (plain dict) renders its sections
    in its key order."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, old_shape_url)
        _enable_families(page, ["CUDA"])
        _open_detail(page, "activemask.b32", "ptx:activemask.b32", "activemask.b32")
        assert _section_summaries(page, "Instruction Semantics") == OLD_ORDER
    finally:
        page.close()
