"""End-to-end browser tests for the static web app.

Drives a headless Chromium against a freshly-built ``web/`` served by
Python's ``http.server``. Covers the kind-filter regression: with
``instructions`` unchecked, searching ``add`` must return intrinsic
hits even though Phase 1 painted with instructions only.

Skips when Playwright or its chromium browser aren't installed so the
suite stays green on minimal CI images.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import threading
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError, sync_playwright  # noqa: E402


REPO_ROOT = Path(__file__).parent.parent

# The web app is a client of `simdref export` output only; this repo ships
# static files and deliberately carries no runtime dependency on the
# `simdref` package (see pyproject's dependency-groups note). The old
# committed fixture was hand-authored against a long-since-renamed export
# schema, so the e2e tests run against a real export via
# SIMDREF_WEB_SITE_DATA (CI sets it in rebuild-site.yml) and skip otherwise.
SITE_DATA = (Path(os.environ["SIMDREF_WEB_SITE_DATA"]) if "SIMDREF_WEB_SITE_DATA" in os.environ
             else None)
if SITE_DATA is None:
    pytest.skip("no site data; set SIMDREF_WEB_SITE_DATA", allow_module_level=True)
FIXTURE_SITE_DATA = SITE_DATA  # kept for test_web_fixes' import
STATIC_FILES = ("index.html", "app.js", "style.css", "favicon.svg", "logo.svg")


def _populate_site(out: Path) -> None:
    """Copy site-data (the committed fixture, or a real export under CI) plus
    this repo's static template files into ``out``, so most local runs need
    no simdref install and no export step."""
    shutil.copytree(SITE_DATA, out, dirs_exist_ok=True)
    for name in STATIC_FILES:
        shutil.copy(REPO_ROOT / "web" / name, out / name)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):  # silence stderr spam
        pass


@contextmanager
def _serve(directory: Path, port: int):
    handler = lambda *a, **k: _QuietHandler(*a, directory=str(directory), **k)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


@pytest.fixture(scope="module")
def web_dir(tmp_path_factory) -> Path:
    """Assemble the static site into a tmp dir: fixture site-data + templates."""
    out = tmp_path_factory.mktemp("web")
    _populate_site(out)
    return out


@pytest.fixture(scope="module")
def page_url(web_dir: Path):
    port = _free_port()
    with _serve(web_dir, port):
        yield f"http://127.0.0.1:{port}/"


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


def _toggle_kind(page, kind: str, checked: bool) -> None:
    """Toggle a kind filter chip and fire its change handler.

    The checkbox itself is visually hidden (the label is styled as a chip),
    so Playwright's `.uncheck()` refuses to click it. Drive it via JS
    instead — mirrors exactly what clicking the label would do.
    """
    page.evaluate(
        """
        ({kind, checked}) => {
            const cb = document.querySelector(`#kind-bar input[data-kind="${kind}"]`);
            if (!cb) throw new Error(`no kind checkbox for ${kind}`);
            if (cb.checked === checked) return;
            cb.checked = checked;
            cb.dispatchEvent(new Event('change', {bubbles: true}));
        }
        """,
        {"kind": kind, "checked": checked},
    )


def _wait_intrinsics_loaded(page) -> None:
    """Block until Phase-2 ingest has folded every intrinsic into the
    search index and buckets, not just fetched the shard.

    ``intrinsicsReady`` is the promise ``_ingestIntrinsics`` returns; it
    resolves only once every entry is pushed into searchEntries/buckets.
    Wait on it directly rather than the transient ``.meta-loading`` badge:
    for this suite's tiny fixture catalog (2 intrinsics, one batch)
    Phase 2 can attach and remove the badge within a single tick, faster
    than DOM polling reliably observes either state.
    """
    page.wait_for_function("() => intrinsicsReady !== null", timeout=15_000)
    page.evaluate("() => intrinsicsReady")


def test_search_add_with_only_intrinsics_returns_intrinsics(browser, page_url):
    """Reproduces the kind-filter regression: disabling instructions then
    searching 'add' must still return intrinsic hits."""
    page = browser.new_page()
    try:
        page.goto(page_url)
        _wait_intrinsics_loaded(page)

        # Uncheck the "instructions" kind chip.
        _toggle_kind(page, "instruction", False)

        page.locator("#query").fill("add")
        # Debounce window is ~90 ms in the app; give it a beat.
        page.wait_for_timeout(300)

        # Wait until at least one result article shows up.
        page.wait_for_selector(".result.intrinsic-kind", timeout=10_000)

        # All visible result cards should be intrinsics.
        kinds = page.eval_on_selector_all(
            ".result",
            "els => els.map(e => e.classList.contains('intrinsic-kind') ? 'i'"
            "       : e.classList.contains('instruction-kind') ? 'a' : '?')",
        )
        assert kinds, "no result cards rendered"
        assert all(k == "i" for k in kinds), (
            f"instructions leaked into result list with kind filter off: {kinds}"
        )

        # And specifically the canonical intrinsics for 'add' must appear.
        keys = page.eval_on_selector_all(
            ".result", "els => els.map(e => e.getAttribute('data-key'))"
        )
        for want in ("_mm_add_ps", "_mm256_add_ps"):
            assert want in keys, f"expected {want} among results; got {keys[:10]}"
    finally:
        page.close()


def test_search_add_with_only_instructions_returns_instructions(browser, page_url):
    """Symmetric check: disabling intrinsics still finds the ADD instruction."""
    page = browser.new_page()
    try:
        page.goto(page_url)
        _wait_intrinsics_loaded(page)

        _toggle_kind(page, "intrinsic", False)
        page.locator("#query").fill("add")
        page.wait_for_timeout(300)
        page.wait_for_selector(".result.instruction-kind", timeout=10_000)

        kinds = page.eval_on_selector_all(
            ".result",
            "els => els.map(e => e.classList.contains('intrinsic-kind') ? 'i'"
            "       : e.classList.contains('instruction-kind') ? 'a' : '?')",
        )
        assert kinds and all(k == "a" for k in kinds), kinds
    finally:
        page.close()


def test_deep_link_to_intrinsic_resolves_after_phase2(browser, page_url):
    """Hash deep-link to an intrinsic must open the detail pane even when
    Phase 2 hasn't finished yet (the hashchange handler awaits the
    intrinsics-ready promise)."""
    page = browser.new_page()
    try:
        page.goto(page_url + "#_mm256_add_ps")
        # Detail pane has the intrinsic name as the heading once loaded.
        page.wait_for_function(
            "() => document.querySelector('#detail') && "
            "document.querySelector('#detail').textContent.includes('_mm256_add_ps')",
            timeout=30_000,
        )
    finally:
        page.close()


def test_schema_version_mismatch_shows_error(browser, tmp_path_factory):
    """A ``build_stamp.json`` with the wrong ``schema_version`` must abort the
    load and surface an error instead of silently misdecoding the columnar
    search-index shards (core bumped the format once already)."""
    out = tmp_path_factory.mktemp("web-bad-schema")
    _populate_site(out)
    stamp = json.loads((out / "build_stamp.json").read_text())
    stamp["schema_version"] = 999
    raw = json.dumps(stamp).encode()
    (out / "build_stamp.json").write_bytes(raw)
    (out / "build_stamp.json.gz").unlink(missing_ok=True)  # force the raw-JSON fetchJson fallback

    port = _free_port()
    with _serve(out, port):
        page = browser.new_page()
        try:
            page.goto(f"http://127.0.0.1:{port}/")
            page.wait_for_function("() => window.__loadError === true", timeout=15_000)
            assert "schema" in page.locator("#detail-empty").text_content().lower()
        finally:
            page.close()
