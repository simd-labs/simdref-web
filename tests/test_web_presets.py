"""Browser tests for the preset-only family contract.

FilterSpec.chip_families names the family chips; CUDA and PTX stay out
of the chip row and are reachable only through presets. The CUDA
preset selects CUDA and PTX and keeps both result kinds, the Default
preset enables no Arm or RISC-V family, an instruction metadata link is
labelled "uops.info" only on that host, and the description sections
render in the record's own key order.

Skips when Playwright or its chromium browser are missing. The shared
server and browser fixtures live in conftest.py.
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
CHIP_FAMILIES = ["SSE", "AVX", "AVX-512", "Arm", "RISC-V"]


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


def _make_site(tmp_path_factory, name, spec_edit=None) -> Path:
    """Assemble the fixture site data, optionally rewriting filter_spec.json."""
    out = tmp_path_factory.mktemp(name)
    shutil.copytree(FIXTURE_SITE_DATA, out, dirs_exist_ok=True)
    for fname in STATIC_FILES:
        shutil.copy(REPO_ROOT / "web" / fname, out / fname)
    if spec_edit:
        spec_path = out / "filter_spec.json"
        spec = json.loads(spec_path.read_text())
        spec_edit(spec)
        spec_path.write_text(json.dumps(spec, indent=2) + "\n")
    return out


@pytest.fixture(scope="module")
def fixture_url(tmp_path_factory):
    out = _make_site(tmp_path_factory, "web-presets")
    port = _free_port()
    with _serve(out, port):
        yield f"http://127.0.0.1:{port}/"


@pytest.fixture(scope="module")
def no_cuda_preset_url(tmp_path_factory):
    def drop_cuda(spec):
        spec.get("presets", {}).pop("cuda", None)

    out = _make_site(tmp_path_factory, "web-presets-fallback", drop_cuda)
    port = _free_port()
    with _serve(out, port):
        yield f"http://127.0.0.1:{port}/"


def _open(page, url):
    page.goto(url)
    page.wait_for_function(
        "() => document.body.dataset.phase2 === 'done'", timeout=60_000, polling=100
    )


def _open_picker(page):
    page.locator("#isa-toggle").click()
    page.wait_for_selector("#isa-panel:not(.hidden)", timeout=10_000)


def _chips(page):
    return page.eval_on_selector_all(
        "#isa-families .isa-chip", "els => els.map(e => e.textContent.trim())"
    )


def _label(page):
    return page.locator("#isa-summary").inner_text()


def _titles(page):
    return page.eval_on_selector_all(
        ".result .result-title", "els => els.map(e => e.textContent.trim())"
    )


def _search(page, query):
    page.locator("#query").fill(query)
    page.wait_for_function(
        "() => document.querySelectorAll('#results .result').length > 0",
        timeout=15_000,
        polling=100,
    )
    page.wait_for_timeout(200)


def test_family_chips_hide_the_preset_only_families(browser, fixture_url):
    """The chip row is chip_families in order: no CUDA or PTX chip."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _open_picker(page)
        assert _chips(page) == CHIP_FAMILIES, _chips(page)
    finally:
        page.close()


def test_cuda_preset_shows_ptx_instruction_rows_with_kind_both(browser, fixture_url):
    """The CUDA preset enables CUDA and PTX with kind both, so a search
    shows the CUDA intrinsic row and the PTX instruction row, and the
    ISA button names both families."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _open_picker(page)
        page.locator("#isa-cuda").click()
        page.wait_for_timeout(300)

        assert _label(page) == "ISA: CUDA, PTX", _label(page)
        kinds = page.eval_on_selector_all(
            "#kind-bar input[data-kind]",
            "els => els.map(e => [e.dataset.kind, e.checked])",
        )
        assert kinds and all(checked for _, checked in kinds), f"kind not both: {kinds}"

        _search(page, "activemask")
        rows = page.eval_on_selector_all(
            "#results .result",
            "els => els.map(e => [e.dataset.key,"
            " e.classList.contains('intrinsic-kind') ? 'intrinsic'"
            " : e.classList.contains('instruction-kind') ? 'instruction' : '?'])",
        )
        as_dict = dict(rows)
        assert as_dict.get("__activemask") == "intrinsic", rows
        assert as_dict.get("ptx:activemask.b32") == "instruction", rows
    finally:
        page.close()


def test_cuda_fallback_preset_selects_cuda_and_ptx(browser, no_cuda_preset_url):
    """With no 'cuda' preset in the data, the built-in fallback still
    selects the CUDA and the PTX family."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, no_cuda_preset_url)
        _open_picker(page)
        page.locator("#isa-cuda").click()
        page.wait_for_timeout(300)

        assert _label(page) == "ISA: CUDA, PTX", _label(page)
        _search(page, "activemask")
        keys = page.eval_on_selector_all("#results .result", "els => els.map(e => e.dataset.key)")
        assert "ptx:activemask.b32" in keys, keys
        assert "__activemask" in keys, keys
    finally:
        page.close()


def test_default_preset_enables_no_arm_or_riscv(browser, fixture_url):
    """The Default preset is x86 SIMD only: no Arm or RISC-V family
    stays enabled and no Arm or RISC-V row stays visible."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        _open_picker(page)
        # The picker shows the chip_families row, in order.
        assert _chips(page) == CHIP_FAMILIES, _chips(page)
        for family in ("Arm", "RISC-V"):
            cb = page.locator(f'#isa-families input[data-family="{family}"]')
            cb.evaluate("el => el.click()")
        page.wait_for_timeout(300)
        assert _label(page) != "ISA: SSE, AVX, AVX-512", _label(page)

        page.locator("#isa-default").click()
        page.wait_for_timeout(300)
        assert _label(page) == "ISA: SSE, AVX, AVX-512", _label(page)
        active = page.eval_on_selector_all(
            "#isa-families .isa-chip",
            "els => els.filter(e => e.classList.contains('active')).map(e => e.textContent.trim())",
        )
        assert not any(a in ("Arm", "RISC-V") for a in active), active

        _search(page, "add")
        badges = page.eval_on_selector_all(
            ".result .result-isa", "els => els.map(e => e.textContent.trim())"
        )
        assert badges, "no rows under Default for 'add'"
        assert not any(b in ("Arm", "NEON", "RISC-V", "V") for b in badges), badges
    finally:
        page.close()


def test_instruction_metadata_link_labels(browser, fixture_url):
    """The metadata link reads 'uops.info' only on that host; any other
    reference URL reads 'Reference'."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)

        def links(hash_key, heading):
            page.goto(fixture_url + "#" + hash_key)
            page.wait_for_function(
                "t => (document.querySelector('#detail h2')?.textContent || '').includes(t)",
                arg=heading,
                timeout=15_000,
                polling=100,
            )
            page.wait_for_function(
                "() => document.querySelectorAll('#detail .kv-links .kv-link').length > 0",
                timeout=15_000,
                polling=100,
            )
            return page.eval_on_selector_all(
                "#detail .kv-links .kv-link",
                "els => els.map(e => [e.textContent.trim(), e.getAttribute('href')])",
            )

        # The CUDA intrinsic's linked instruction sits on docs.nvidia.com.
        cuda = links("__activemask", "__activemask")
        assert any(
            t == "Reference" and "parallel-thread-execution" in (h or "") for t, h in cuda
        ), cuda

        # The PTX instruction's own URL also reads "Reference".
        ptx = links("ptx%3Aactivemask.b32", "activemask.b32")
        assert any(t == "Reference" for t, _ in ptx), ptx
        assert not any(t == "uops.info" for t, _ in ptx), ptx

        # A uops.info row keeps the site name, at both link sites.
        vaddps = links("x86%3Avaddps%20(ymm%2C%20ymm%2C%20ymm)", "VADDPS (YMM, YMM, YMM)")
        assert any(t == "uops.info" and "uops.info" in (h or "") for t, h in vaddps), vaddps
        mm = links("_mm256_add_ps", "_mm256_add_ps")
        assert any(t == "uops.info" and "uops.info" in (h or "") for t, h in mm), mm
    finally:
        page.close()


def test_description_sections_keep_the_record_key_order(browser, fixture_url):
    """Sections render in the record's own key order (doc page order),
    never sorted or hoisted."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open(page, fixture_url)
        page.goto(fixture_url + "#ptx%3Aactivemask.b32")
        page.wait_for_function(
            "t => (document.querySelector('#detail h2')?.textContent || '').includes(t)",
            arg="activemask.b32",
            timeout=15_000,
            polling=100,
        )
        page.wait_for_function(
            "() => document.querySelectorAll('#detail .desc-section summary').length > 0",
            timeout=15_000,
            polling=100,
        )
        heads = page.eval_on_selector_all(
            "#detail .desc-section summary", "els => els.map(e => e.textContent.trim())"
        )
        assert heads == [
            "Syntax",
            "Description",
            "Examples",
            "PTX ISA Notes",
            "Target ISA Notes",
        ], heads
    finally:
        page.close()
