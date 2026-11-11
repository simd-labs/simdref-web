"""Browser test: the CUDA preset selects only the CUDA family.

Clicking the CUDA preset button (between RISC-V and None) must activate
only the CUDA family chip, name the toggle label "CUDA", and restrict a
search for ``__shfl_sync`` to CUDA-only results.

Skips when Playwright or its chromium browser aren't installed so the
suite stays green on minimal CI images. The shared harness (site
assembly, server, browser fixtures) lives in conftest.py.
"""

from __future__ import annotations


def _open_picker(page) -> None:
    """Open the ISA picker panel and wait until it is visible."""
    page.locator("#isa-toggle").click()
    page.wait_for_selector("#isa-panel:not(.hidden)", timeout=10_000)


def test_cuda_preset_selects_only_cuda_family(browser, page_url):
    """The CUDA preset activates only the CUDA chip, labels the toggle
    'CUDA', and a __shfl_sync search returns CUDA-only results."""
    page = browser.new_page()
    try:
        page.goto(page_url)
        page.wait_for_function("() => document.body.dataset.phase2 === 'done'", timeout=60_000)

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

        # Only the CUDA chip is active.
        active = page.eval_on_selector_all(
            "#isa-families .isa-chip",
            "els => els.filter(e => e.classList.contains('active')).map(e => e.textContent.trim())",
        )
        assert active == ["CUDA"], f"expected only CUDA active, got {active}"

        # The toggle label names CUDA.
        label = page.locator("#isa-summary").inner_text()
        assert label == "ISA: CUDA", f"expected 'ISA: CUDA', got {label!r}"

        # A search for __shfl_sync lists only CUDA results.
        page.locator("#query").fill("__shfl_sync")
        page.wait_for_timeout(400)
        page.wait_for_selector(".result", timeout=10_000)

        isas = page.eval_on_selector_all(
            ".result .result-isa", "els => els.map(e => e.textContent.trim())"
        )
        assert isas, "no results for __shfl_sync"
        assert all(i == "CUDA" for i in isas), f"expected only CUDA results, got {isas}"
    finally:
        page.close()
