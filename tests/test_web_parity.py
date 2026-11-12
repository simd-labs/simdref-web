"""Browser tests for the TUI-parity keys and detail controls.

f expands or collapses every detail section (TUI toggle_all), i toggles
the ISA panel, and the key help names both. Each test fails on
origin/main: there f toggles the ISA panel, i does nothing, and the
help lists "f Toggle ISA filter".
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError, sync_playwright  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from conftest import FIXTURE_SITE_DATA, STATIC_FILES, _free_port, _serve  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent
ACT_KEY = "#ptx%3Aactivemask.b32"


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
def parity_url(tmp_path_factory):
    out = tmp_path_factory.mktemp("web-parity")
    shutil.copytree(FIXTURE_SITE_DATA, out, dirs_exist_ok=True)
    for fname in STATIC_FILES:
        shutil.copy(REPO_ROOT / "web" / fname, out / fname)
    port = _free_port()
    with _serve(out, port):
        yield f"http://127.0.0.1:{port}/"


@pytest.fixture(scope="module")
def sparse_url(tmp_path_factory):
    """Fixture site whose chip_families names a family with no rows."""
    out = tmp_path_factory.mktemp("web-parity-sparse")
    shutil.copytree(FIXTURE_SITE_DATA, out, dirs_exist_ok=True)
    for fname in STATIC_FILES:
        shutil.copy(REPO_ROOT / "web" / fname, out / fname)
    spec_path = out / "filter_spec.json"
    spec = json.loads(spec_path.read_text())
    spec["chip_families"] = [*spec["chip_families"], "SVE"]
    spec_path.write_text(json.dumps(spec, indent=2) + "\n")
    port = _free_port()
    with _serve(out, port):
        yield f"http://127.0.0.1:{port}/"


def _open_act(page, url):
    page.goto(url + ACT_KEY)
    page.wait_for_function(
        "() => document.body.dataset.phase2 === 'done'", timeout=60_000, polling=100
    )
    page.wait_for_function(
        "() => document.querySelectorAll('#detail .desc-section').length >= 5",
        timeout=15_000,
        polling=100,
    )


def _section_state(page):
    return page.eval_on_selector_all("#detail details", "els => els.map(e => e.open)")


def test_f_key_expands_and_collapses_every_detail_section(browser, parity_url):
    """f opens every detail section and the next f closes them all."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open_act(page, parity_url)
        state = _section_state(page)
        assert state and not any(state), state
        # Results focus must not divert f into type-to-refine.
        page.evaluate("document.getElementById('results').focus()")
        page.keyboard.press("f")
        page.wait_for_timeout(200)
        state = _section_state(page)
        assert state and all(state), state
        assert page.evaluate("document.querySelector('#query').value") == ""
        page.keyboard.press("f")
        page.wait_for_timeout(200)
        state = _section_state(page)
        assert state and not any(state), state
    finally:
        page.close()


def test_new_sections_follow_the_expand_all_flag(browser, parity_url):
    """A detail rendered after f keeps every section open (TUI parity)."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open_act(page, parity_url)
        page.keyboard.press("f")
        page.wait_for_timeout(200)
        # Same page, second entry: the flag must carry into its render.
        page.locator("#isa-toggle").click()
        page.locator("#isa-cuda").click()
        page.wait_for_timeout(300)
        page.locator("#query").fill("activemask")
        page.wait_for_function(
            "() => document.querySelectorAll('#results .result').length >= 2",
            timeout=15_000,
            polling=100,
        )
        page.locator("#results .result").nth(1).click()
        page.wait_for_function(
            "() => document.querySelectorAll('#detail .desc-section').length >= 1",
            timeout=15_000,
            polling=100,
        )
        state = _section_state(page)
        assert state and all(state), state
    finally:
        page.close()


def test_i_key_toggles_the_isa_panel_and_the_help_lists_both_keys(browser, parity_url):
    """i opens and closes the ISA panel; the help table names f and i."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open_act(page, parity_url)
        hidden0 = page.evaluate("document.querySelector('#isa-panel').classList.contains('hidden')")
        assert hidden0
        page.keyboard.press("i")
        page.wait_for_timeout(150)
        assert not page.evaluate(
            "document.querySelector('#isa-panel').classList.contains('hidden')"
        )
        page.keyboard.press("i")
        page.wait_for_timeout(150)
        assert page.evaluate("document.querySelector('#isa-panel').classList.contains('hidden')")
        page.keyboard.press("?")
        page.wait_for_timeout(150)
        rows = page.eval_on_selector_all(
            "#shortcuts-overlay .shortcuts-table tr",
            "els => els.map(r => r.textContent.trim())",
        )
        assert any(r.startswith("f") and "Expand/Collapse All" in r for r in rows), rows
        assert any(r.startswith("i") and "Toggle ISA filter" in r for r in rows), rows
    finally:
        page.close()


def test_expand_collapse_all_control_lives_in_the_detail_pane(browser, parity_url):
    """The detail-pane control does what the f key does."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open_act(page, parity_url)
        btn = page.locator("#detail .detail-all")
        assert btn.count() == 1, f"detail control count: {btn.count()}"
        assert btn.inner_text() == "Expand/Collapse All"
        state = _section_state(page)
        assert state and not any(state), state
        btn.click()
        page.wait_for_timeout(200)
        state = _section_state(page)
        assert state and all(state), state
        btn.click()
        page.wait_for_timeout(200)
        state = _section_state(page)
        assert state and not any(state), state
    finally:
        page.close()


def test_digit_keys_pick_a_result_by_row_number(browser, parity_url):
    """1-9 select that result row and show its detail (TUI pick)."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open_act(page, parity_url)
        page.locator("#query").fill("add")
        page.wait_for_function(
            "() => document.querySelectorAll('#results .result').length >= 3",
            timeout=15_000,
            polling=100,
        )
        page.evaluate("document.activeElement.blur()")
        before = page.evaluate("document.querySelector('#query').value")
        old = page.evaluate("document.querySelector('#detail h2')?.textContent.trim()")
        page.keyboard.press("3")
        page.wait_for_timeout(400)
        shown = page.evaluate("document.querySelector('#detail h2')?.textContent.trim()")
        page.locator("#results .result").nth(2).click()
        page.wait_for_function(
            "t => document.querySelector('#detail h2')?.textContent.trim() !== t",
            arg=old,
            timeout=15_000,
            polling=100,
        )
        clicked = page.evaluate("document.querySelector('#detail h2')?.textContent.trim()")
        assert shown != old, f"digit 3 did not change the detail: {shown}"
        assert shown == clicked, (shown, clicked)
        assert page.evaluate("document.querySelector('#query').value") == before
    finally:
        page.close()


def test_ctrl_arrow_keys_move_the_annotate_split(browser, parity_url):
    """Ctrl+left and Ctrl+right step the split by 5% (TUI ann_split)."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open_act(page, parity_url)
        page.locator("#tab-annotate").click()
        page.wait_for_timeout(300)
        ratio = lambda: page.evaluate(
            "parseFloat(document.querySelector('#ann-panes').style.getPropertyValue('--ann-split'))"
        )
        r0 = ratio()
        page.keyboard.press("Control+ArrowRight")
        page.wait_for_timeout(150)
        r1 = ratio()
        assert abs(r1 - (r0 + 0.05)) < 0.001, (r0, r1)
        page.keyboard.press("Control+ArrowLeft")
        page.keyboard.press("Control+ArrowLeft")
        page.wait_for_timeout(150)
        r2 = ratio()
        assert abs(r2 - (r0 - 0.05)) < 0.001, (r0, r2)
    finally:
        page.close()


def test_chip_row_keeps_a_chip_families_entry_with_no_rows(browser, sparse_url):
    """Every chip_families entry is a chip even with no rows (TUI parity)."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(sparse_url)
        page.wait_for_function(
            "() => document.body.dataset.phase2 === 'done'", timeout=60_000, polling=100
        )
        page.locator("#isa-toggle").click()
        page.wait_for_selector("#isa-panel:not(.hidden)", timeout=10_000)
        chips = page.eval_on_selector_all(
            "#isa-families .isa-chip", "els => els.map(e => e.textContent.trim())"
        )
        assert chips == ["SSE", "AVX", "AVX-512", "Arm", "RISC-V", "SVE"], chips

        # The row-less chip still toggles.
        def _active():
            return page.eval_on_selector_all(
                "#isa-families .isa-chip",
                "els => els.filter(e => e.classList.contains('active'))"
                ".map(e => e.textContent.trim())",
            )

        before = _active()
        assert "SVE" not in before, before
        page.locator('#isa-families input[data-family="SVE"]').evaluate("el => el.click()")
        page.wait_for_timeout(200)
        after = _active()
        assert "SVE" in after, after
    finally:
        page.close()
