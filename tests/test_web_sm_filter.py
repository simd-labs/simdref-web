"""Browser tests: the SM chip filters CUDA/PTX rows by their shard floor.

The chip reads FilterSpec.sm_levels and shows only for a CUDA/PTX
selection. A row passes the chosen level when its floor is null or at
most that level (simdref filters.runs_on_sm); other families never hide.
Fixture floors: __shfl_sync sm_70, __shfl_down_sync sm_50, __shfl_up_sync
and __shfl_xor_sync null, shfl.sync.b32 (PTX) sm_70, __match_any_sync
sm_70, __match_all_sync sm_90. The x86 rows carry sm_90 floors on
purpose: only the family gate keeps them visible at sm_50.
"""

from __future__ import annotations

import json

import pytest

SHARDS = ("search-index-instructions.json", "search-index-intrinsics.json")


def _require_sm_data(web_dir) -> None:
    """Skip on a site export that predates the sm column contract."""
    spec_path = web_dir / "filter_spec.json"
    spec = json.loads(spec_path.read_text()) if spec_path.exists() else {}
    if not spec.get("sm_levels"):
        pytest.skip("site data lists no sm_levels")
    for name in SHARDS:
        shard = json.loads((web_dir / name).read_text())
        if "sm" not in (shard.get("cols") or {}):
            pytest.skip("site data shards carry no sm floors")


def _open_picker(page) -> None:
    page.locator("#isa-toggle").click()
    page.wait_for_selector("#isa-panel:not(.hidden)", timeout=10_000)


def _pick_sm(page, level: str) -> None:
    page.locator("#sm-chips label").filter(has_text=level).click()
    page.wait_for_timeout(300)


def _titles(page) -> list[str]:
    return page.eval_on_selector_all(
        ".result .result-title", "els => els.map(e => e.textContent.trim())"
    )


def _boot(page, page_url) -> None:
    page.goto(page_url)
    page.wait_for_function("() => document.body.dataset.phase2 === 'done'", timeout=60_000)


def test_sm_50_hides_an_sm_70_row_and_sm_90_shows_it(browser, page_url, web_dir):
    """CUDA rows and PTX rows obey the floor rule at sm_50 and sm_90."""
    _require_sm_data(web_dir)
    page = browser.new_page()
    try:
        _boot(page, page_url)
        _open_picker(page)
        page.locator("#isa-cuda").click()
        page.wait_for_timeout(300)
        assert page.locator("#sm-group").is_visible(), "SM chip missing under the CUDA preset"

        page.locator("#query").fill("shfl")
        page.wait_for_timeout(400)
        _pick_sm(page, "sm_50")
        titles = _titles(page)
        assert "__shfl_sync" not in titles, titles
        assert "__shfl_down_sync" in titles, titles
        assert "__shfl_xor_sync" in titles, titles

        _pick_sm(page, "sm_90")
        titles = _titles(page)
        assert "__shfl_sync" in titles, titles

        # The PTX instruction shard obeys the same rule.
        page.locator("#isa-families label").filter(has_text="PTX").click()
        page.wait_for_timeout(300)
        ptx = "shfl.sync.b32 d[|p], a, b, c, membermask"
        _pick_sm(page, "sm_50")
        titles = _titles(page)
        assert ptx not in titles, titles
        _pick_sm(page, "sm_90")
        titles = _titles(page)
        assert ptx in titles, titles
    finally:
        page.close()


def test_null_floor_row_stays_at_sm_50(browser, page_url, web_dir):
    """A CUDA row with no floor passes every level; the sm_70 row still hides."""
    _require_sm_data(web_dir)
    page = browser.new_page()
    try:
        _boot(page, page_url)
        _open_picker(page)
        page.locator("#isa-cuda").click()
        page.wait_for_timeout(300)
        page.locator("#query").fill("shfl")
        page.wait_for_timeout(400)
        _pick_sm(page, "sm_50")
        titles = _titles(page)
        assert "__shfl_up_sync" in titles, titles
        assert "__shfl_xor_sync" in titles, titles
        assert "__shfl_sync" not in titles, titles
    finally:
        page.close()


def test_x86_row_stays_under_the_sm_filter(browser, page_url, web_dir):
    """Rows of other families pass even with a floor above the choice.

    The fixture x86 rows carry sm_90 floors, so only the family gate
    keeps them visible at sm_50.
    """
    _require_sm_data(web_dir)
    page = browser.new_page()
    try:
        _boot(page, page_url)
        _open_picker(page)
        page.locator("#isa-families label").filter(has_text="CUDA").click()
        page.wait_for_timeout(300)
        page.locator("#query").fill("add")
        page.wait_for_timeout(400)
        _pick_sm(page, "sm_50")
        picked = page.eval_on_selector("#sm-chips input[value='sm_50']", "el => el.checked")
        assert picked, "the sm_50 chip did not take the selection"
        titles = _titles(page)
        assert "_mm_add_ps" in titles, titles
        assert "_mm256_add_ps" in titles, titles
        assert "ADDPS (XMM, XMM)" in titles, titles
    finally:
        page.close()


def test_sm_chip_hidden_without_cuda_or_ptx(browser, page_url, web_dir):
    """The chip appears only for a CUDA or PTX family selection."""
    _require_sm_data(web_dir)
    page = browser.new_page()
    try:
        _boot(page, page_url)
        _open_picker(page)
        group = page.locator("#sm-group")
        assert not group.is_visible(), "SM chip visible with only x86 families"
        page.locator("#isa-families label").filter(has_text="CUDA").click()
        page.wait_for_timeout(300)
        assert group.is_visible(), "SM chip hidden with CUDA selected"
        page.locator("#isa-families label").filter(has_text="CUDA").click()
        page.wait_for_timeout(300)
        assert not group.is_visible(), "SM chip visible with CUDA deselected"
        page.locator("#isa-families label").filter(has_text="PTX").click()
        page.wait_for_timeout(300)
        assert group.is_visible(), "SM chip hidden with PTX selected"
    finally:
        page.close()


def test_hidden_rows_message_and_persistence(browser, page_url, web_dir):
    """An empty result the SM filter caused reads as one hidden-rows line.

    The choice persists across a reload like the preset choice.
    """
    _require_sm_data(web_dir)
    page = browser.new_page()
    try:
        _boot(page, page_url)
        _open_picker(page)
        page.locator("#isa-cuda").click()
        page.wait_for_timeout(300)
        _pick_sm(page, "sm_50")
        page.locator("#query").fill("match")
        page.wait_for_timeout(400)
        note = page.locator(".sm-hidden-note")
        assert note.count() == 1, f"expected one hidden-rows line, got {note.count()}"
        assert note.inner_text() == "2 rows hidden by the SM filter"
        assert _titles(page) == []

        page.reload()
        page.wait_for_function("() => document.body.dataset.phase2 === 'done'", timeout=60_000)
        _open_picker(page)
        picked = page.eval_on_selector("#sm-chips input[value='sm_50']", "el => el.checked")
        assert picked, "the sm_50 choice did not survive a reload"
        page.locator("#query").fill("match")
        page.wait_for_timeout(400)
        assert page.locator(".sm-hidden-note").inner_text() == "2 rows hidden by the SM filter"
    finally:
        page.close()
