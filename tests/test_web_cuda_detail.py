"""Browser tests for the CUDA detail-page display defects.

One Playwright test per defect, run on the committed fixture site data
whatever SIMDREF_WEB_SITE_DATA points at:

F1: a CUDA row and the CUDA detail show the arch text twice, once as the
    arch badge and once as the ISA badge. The second badge must render
    only when its text differs from the first.
F2: the doc-sections block of a CUDA row is titled "ACLE Documentation".
    The title must come from the record's doc source, Arm rows must keep
    "ACLE documentation", and a record with no doc source must fall back
    to "Documentation".
F3: the metadata "Instruction" chip of __shfl_sync shows the PTX operand
    list. It must show the linked instruction's mnemonic.

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


@pytest.fixture(scope="module")
def fixture_url(tmp_path_factory):
    """Serve the committed fixture site data, never a real export."""
    out = tmp_path_factory.mktemp("cuda-detail-web")
    shutil.copytree(FIXTURE_SITE_DATA, out, dirs_exist_ok=True)
    for name in STATIC_FILES:
        shutil.copy(REPO_ROOT / "web" / name, out / name)
    port = _free_port()
    with _serve(out, port):
        yield f"http://127.0.0.1:{port}/"


def _open(page, url):
    page.goto(url)
    page.wait_for_function(
        "() => document.body.dataset.phase2 === 'done'", timeout=60_000, polling=100
    )


def _enable_families(page, families):
    """Switch the named ISA families on in the picker."""
    page.locator("#isa-toggle").click()
    page.wait_for_selector("#isa-panel:not(.hidden)", timeout=10_000)
    for family in families:
        # The checkbox hides inside its label, so click it through the DOM.
        cb = page.locator(f'#isa-families input[data-family="{family}"]')
        if not cb.is_checked():
            cb.evaluate("el => el.click()")
    page.wait_for_timeout(300)


def _search(page, query, *keys):
    page.locator("#query").fill(query)
    for key in keys:
        # The row of the previous query can still show while the new one
        # renders, so wait for the wanted row instead of any row.
        page.wait_for_function(
            "key => Array.from(document.querySelectorAll('#results .result'))"
            ".some(r => r.dataset.key === key)",
            arg=key,
            timeout=15_000,
            polling=100,
        )


def _open_detail(page, query, key):
    _search(page, query, key)
    page.evaluate(
        "key => Array.from(document.querySelectorAll('#results .result'))"
        ".find(r => r.dataset.key === key)?.click()",
        key,
    )
    page.wait_for_function(
        "key => (document.querySelector('#detail h2')?.textContent || '').includes(key)",
        arg=key,
        timeout=15_000,
        polling=100,
    )
    page.wait_for_function(
        "() => document.querySelector('#detail .kv-compact')", timeout=15_000, polling=100
    )


def _row_badges(page):
    return page.eval_on_selector_all(
        ".result",
        "els => Object.fromEntries(els.map(e => [e.dataset.key,"
        " [...e.querySelectorAll('.result-isa')].map(s => s.textContent.trim())]))",
    )


def _doc_headings(page):
    return page.eval_on_selector_all(
        "#detail section.section h3", "els => els.map(e => e.textContent.trim())"
    )


def test_f1_row_and_detail_show_the_cuda_badge_once(browser, fixture_url):
    """A CUDA row keeps one badge when arch and ISA carry the same text.
    A row whose two labels differ keeps both. The detail shows the CUDA
    text once in its metadata chips."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA", "Arm", "PTX"])

        _search(page, "__shfl_sync", "__shfl_sync")
        badges = _row_badges(page)
        cuda = {k: v for k, v in badges.items() if k.startswith("__shfl")}
        assert cuda, f"no CUDA rows for __shfl_sync: {badges}"
        assert all(v == ["CUDA"] for v in cuda.values()), f"row repeats the CUDA badge: {cuda}"

        _search(page, "_mm_add_ps", "_mm_add_ps")
        badges = _row_badges(page)
        assert badges.get("_mm_add_ps") == ["x86", "SSE"], badges

        _search(page, "vadd_s32", "vadd_s32")
        badges = _row_badges(page)
        assert badges.get("vadd_s32") == ["Arm", "NEON"], badges

        _open_detail(page, "__shfl_sync", "__shfl_sync")
        values = page.eval_on_selector_all(
            "#detail .kv-chip-v", "els => els.map(e => e.textContent.trim())"
        )
        assert values.count("CUDA") == 1, f"detail repeats the CUDA badge: {values}"
    finally:
        page.close()


def test_f2_doc_section_title_comes_from_the_record(browser, fixture_url):
    """The doc-sections heading names the record's doc source. Arm rows
    keep "ACLE documentation", and a record with no doc source falls back
    to "Documentation"."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA", "Arm"])

        # metadata.doc_source "cuda-guide" names the block.
        _open_detail(page, "__shfl_sync", "__shfl_sync")
        heads = _doc_headings(page)
        assert "cuda guide documentation" in heads, heads
        assert not any(h.lower() == "acle documentation" for h in heads), heads

        # A record with only a url falls back to the plain heading.
        _open_detail(page, "__shfl_up_sync", "__shfl_up_sync")
        heads = _doc_headings(page)
        assert "Documentation" in heads, heads

        # An Intel row keeps the url host out of the heading.
        _open_detail(page, "_mm_add_ps", "_mm_add_ps")
        heads = _doc_headings(page)
        assert "Documentation" in heads, heads

        # A record with no doc source and no url falls back.
        _open_detail(page, "__shfl_xor_sync", "__shfl_xor_sync")
        heads = _doc_headings(page)
        assert "Documentation" in heads, heads

        # Arm rows keep "ACLE documentation".
        _open_detail(page, "vadd_s32", "vadd_s32")
        heads = _doc_headings(page)
        assert "ACLE documentation" in heads, heads
    finally:
        page.close()


def test_f3_instruction_chip_shows_the_mnemonic(browser, fixture_url):
    """The metadata "Instruction" chip names the linked instruction's
    mnemonic, never its operand list."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _enable_families(page, ["CUDA"])
        _open_detail(page, "__shfl_sync", "__shfl_sync")
        pairs = page.eval_on_selector_all(
            "#detail .kv-chip",
            "els => els.map(e => [e.querySelector('.kv-chip-k').textContent.trim(),"
            " e.querySelector('.kv-chip-v').textContent.trim()])",
        )
        instr = [v for k, v in pairs if k == "Instruction"]
        assert instr == ["shfl.sync.b32"], pairs
        assert not any("membermask" in (v or "") for _, v in pairs), pairs
    finally:
        page.close()
