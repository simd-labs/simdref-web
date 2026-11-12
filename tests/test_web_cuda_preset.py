"""Browser test: the CUDA preset selects the CUDA and PTX families.

Clicking the CUDA preset button (between RISC-V and None) must enable
the preset-only CUDA and PTX families without a chip for either, name
the toggle label "CUDA, PTX", and keep both result kinds on.

Skips when Playwright or its chromium browser aren't installed so the
suite stays green on minimal CI images. The shared harness (site
assembly, server, browser fixtures) lives in conftest.py.
"""

from __future__ import annotations


def _open_picker(page) -> None:
    """Open the ISA picker panel and wait until it is visible."""
    page.locator("#isa-toggle").click()
    page.wait_for_selector("#isa-panel:not(.hidden)", timeout=10_000)


def test_cuda_preset_selects_cuda_and_ptx_families(browser, page_url):
    """The CUDA preset enables CUDA and PTX with no chips for either,
    labels the toggle 'CUDA, PTX', and keeps both result kinds on."""
    page = browser.new_page()
    try:
        page.goto(page_url)
        page.wait_for_function(
            "() => document.body.dataset.phase2 === 'done'", timeout=60_000, polling=100
        )

        _open_picker(page)

        # The CUDA button must sit between RISC-V and None.
        order = page.eval_on_selector_all(".isa-presets .preset-btn", "els => els.map(e => e.id)")
        assert "isa-cuda" in order, f"CUDA button missing from presets: {order}"
        assert order.index("isa-riscv") + 1 == order.index("isa-cuda"), (
            f"CUDA button must follow RISC-V: {order}"
        )
        assert order.index("isa-cuda") + 1 == order.index("isa-none"), (
            f"CUDA button must precede None: {order}"
        )

        # Click the CUDA preset.
        page.locator("#isa-cuda").click()
        page.wait_for_timeout(300)

        # Only the preset-only families are on, and no chip shows them.
        active = page.eval_on_selector_all(
            "#isa-families .isa-chip",
            "els => els.filter(e => e.classList.contains('active')).map(e => e.textContent.trim())",
        )
        assert active == [], f"expected no active family chip, got {active}"
        chips = page.eval_on_selector_all(
            "#isa-families .isa-chip",
            "els => els.map(e => e.textContent.trim())",
        )
        assert not any(c in ("CUDA", "PTX") for c in chips), (
            f"preset-only families as chips: {chips}"
        )

        # The toggle label names CUDA and PTX.
        label = page.locator("#isa-summary").inner_text()
        assert label == "ISA: CUDA, PTX", f"expected 'ISA: CUDA, PTX', got {label!r}"

        # The kind bar keeps both kinds on: intrinsic and instruction rows.
        kinds = page.eval_on_selector_all(
            "#kind-bar input[data-kind]",
            "els => els.map(e => [e.dataset.kind, e.checked])",
        )
        assert kinds and all(checked for _, checked in kinds), f"kind not both: {kinds}"

        # At phone width (390x844) the preset row must wrap inside the
        # viewport: every .preset-btn lies inside the viewport and keeps a
        # single-line height equal to the first button.
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(200)
        btns = page.eval_on_selector_all(
            ".isa-presets .preset-btn",
            "els => els.map(e => e.getBoundingClientRect())",
        )
        assert all(b["right"] <= 390 for b in btns), f"preset buttons overflow viewport: {btns}"
        assert all(abs(b["height"] - btns[0]["height"]) < 1 for b in btns), (
            f"preset buttons have differing heights: {btns}"
        )

        # A search for __shfl_sync lists only CUDA and PTX results.
        page.locator("#query").fill("__shfl_sync")
        page.wait_for_timeout(400)
        page.wait_for_selector(".result", timeout=10_000)

        isas = page.eval_on_selector_all(
            ".result .result-isa", "els => els.map(e => e.textContent.trim())"
        )
        assert isas, "no results for __shfl_sync"
        assert any(i == "CUDA" for i in isas), f"no CUDA results: {isas}"
        assert all(i in ("CUDA", "ptx", "PTX") for i in isas), (
            f"expected only CUDA/PTX results, got {isas}"
        )
    finally:
        page.close()
