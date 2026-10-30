"""Byte identity tests for the Annotate tab.

Drives the real site in headless Chromium against a fixture server that
serves the real ``search-index-encodings.json`` shard and the local
llvm-mc / XED wasm builds (nothing is fetched from GitHub). Compared
per line against the expected rows of the reference implementation
(src/simdref/asm_identity.py, schema-14 catalog).

The fixture directory (documents, expected rows, shard, wasm builds) is
pointed at through ``SIMDREF_WEB_IDENTITY_DIR``; the tests skip when it
is unset, so minimal CI images stay green. Layout::

    doc-att.s / expected-att.json   AT&T x86 corpus document + rows
    doc-a64.s / expected-a64.json   AArch64 corpus document + rows
    search-index-encodings.json     the real export shard
    wasm/       hash-matching llvm-mc/xedform builds
    wasm-bad/   the same, with one byte of llvm-mc.wasm flipped
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from test_web_e2e import _free_port, _populate_site, _serve  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent
IDIR = (
    Path(os.environ["SIMDREF_WEB_IDENTITY_DIR"])
    if "SIMDREF_WEB_IDENTITY_DIR" in os.environ
    else None
)

requires_fixtures = pytest.mark.skipif(IDIR is None, reason="SIMDREF_WEB_IDENTITY_DIR not set")

WASM_FILES = ("llvm-mc.js", "llvm-mc.wasm", "xedform.cjs", "xedform.wasm")


def _build_site(out: Path, wasm_source: Path) -> None:
    _populate_site(out)
    shutil.copy(REPO_ROOT / "web" / "identity.js", out / "identity.js")
    shutil.copy(IDIR / "search-index-encodings.json", out / "search-index-encodings.json")
    wasm_dir = out / "wasm-v1"
    wasm_dir.mkdir()
    for name in WASM_FILES:
        shutil.copy(wasm_source / name, wasm_dir / name)


@pytest.fixture(scope="module")
def browser():
    try:
        pw = sync_playwright().start()
    except Exception as exc:
        pytest.skip(f"playwright unavailable: {exc}")
    try:
        b = pw.chromium.launch(headless=True)
    except Exception as exc:
        pw.stop()
        pytest.skip(f"chromium not installed for playwright: {exc}")
    try:
        yield b
    finally:
        b.close()
        pw.stop()


@requires_fixtures
@pytest.mark.parametrize("cls,isa", [("att", "x86"), ("a64", "arm"), ("riscv", "riscv")])
def test_corpus_rows_match_asm_identity(browser, cls, isa, tmp_path):
    """Every corpus line gets the same catalog row as asm_identity."""
    site = tmp_path / "site"
    _build_site(site, IDIR / "wasm")
    document = (IDIR / f"doc-{cls}.s").read_text().rstrip("\n")
    expected = json.loads((IDIR / f"expected-{cls}.json").read_text())
    port = _free_port()
    with _serve(site, port):
        page = browser.new_page()
        try:
            page.add_init_script("window.__simdrefWasmBase = location.origin + '/wasm-v1/';")
            page.goto(f"http://127.0.0.1:{port}/")
            actual = page.evaluate(
                "(args) => resolveIdentityKeys(args.text, args.isa)",
                {"text": document, "isa": isa},
            )
        finally:
            page.close()
    assert actual is not None, "identity worker unavailable"
    agree = 0
    disagreements = []
    for want, got in zip(expected, actual):
        if (
            want["n"] == got["n"]
            and want["status"] == got["status"]
            and want["key"] == got.get("key")
        ):
            agree += 1
        elif len(disagreements) < 10:
            disagreements.append((want, got))
    disagree = len(expected) - agree
    assert len(actual) == len(expected), f"line counts differ: {len(actual)} vs {len(expected)}"
    assert disagree == 0, (
        f"{cls}: {agree}/{len(expected)} agree, {disagree} disagree; first:\n"
        + "\n".join(f"want {w['n']} {w['status']} {w['key']} got {g}" for w, g in disagreements)
    )
    print(f"{cls}: {agree}/{len(expected)} agree, {disagree} disagree")


@requires_fixtures
def test_trailing_newline_keeps_identity(browser, tmp_path):
    """A document ending in "\n" has no phantom last line (Python's
    splitlines() semantics); without that, the echo-lockstep count
    mismatches and every line ends unknown."""
    site = tmp_path / "site"
    _build_site(site, IDIR / "wasm")
    expected = json.loads((IDIR / "expected-att.json").read_text())
    document = "\n".join(w["text"] for w in expected[:5]) + "\n"
    port = _free_port()
    with _serve(site, port):
        page = browser.new_page()
        try:
            page.add_init_script("window.__simdrefWasmBase = location.origin + '/wasm-v1/';")
            page.goto(f"http://127.0.0.1:{port}/")
            actual = page.evaluate(
                "(args) => resolveIdentityKeys(args.text, args.isa)",
                {"text": document, "isa": "x86"},
            )
        finally:
            page.close()
    assert actual is not None
    assert actual[0]["status"] == "row" and actual[0]["key"] == expected[0]["key"], actual[0]


@requires_fixtures
def test_crlf_and_form_feed_split_like_splitlines(browser, tmp_path):
    """Line terminators never ride on the line (Python's splitlines()):
    \r\n and a form feed split, so the per-line rows line up with the
    document the user sees."""
    site = tmp_path / "site"
    _build_site(site, IDIR / "wasm")
    expected = json.loads((IDIR / "expected-att.json").read_text())
    texts = [expected[0]["text"], "\x0c", expected[1]["text"]]
    document = "\r\n".join(texts) + "\r\n"
    port = _free_port()
    with _serve(site, port):
        page = browser.new_page()
        try:
            page.add_init_script("window.__simdrefWasmBase = location.origin + '/wasm-v1/';")
            page.goto(f"http://127.0.0.1:{port}/")
            actual = page.evaluate(
                "(args) => resolveIdentityKeys(args.text, args.isa)",
                {"text": document, "isa": "x86"},
            )
        finally:
            page.close()
    assert actual is not None and len(actual) == 4, actual
    assert actual[0]["status"] == "row" and actual[0]["key"] == expected[0]["key"], actual[0]
    assert actual[1]["status"] == "not-an-instruction", actual[1]
    assert actual[2]["status"] == "not-an-instruction", actual[2]
    assert actual[3]["status"] == "row" and actual[3]["key"] == expected[1]["key"], actual[3]


def _identify_doc(browser, tmp_path, document, isa="x86"):
    """Run one document through the identity worker on the real site."""
    site = tmp_path / f"site{len(list(tmp_path.iterdir()))}"
    _build_site(site, IDIR / "wasm")
    port = _free_port()
    with _serve(site, port):
        page = browser.new_page()
        try:
            page.add_init_script("window.__simdrefWasmBase = location.origin + '/wasm-v1/';")
            page.goto(f"http://127.0.0.1:{port}/")
            return page.evaluate(
                "(args) => resolveIdentityKeys(args.text, args.isa)",
                {"text": document, "isa": isa},
            )
        finally:
            page.close()


@requires_fixtures
def test_semicolon_separator_keeps_each_row(browser, tmp_path):
    """';' is a statement separator for llvm-mc x86 AT&T, so the line
    after it keeps its own row and never the cmp row of the line above
    (probe: 'GOT x86:cmp (i32, i32, i32) WANT x86:test (i32, i32)')."""
    actual = _identify_doc(
        browser, tmp_path, "\tcmpl %eax, %ecx\n; comment line\n\ttestl %eax, %ecx\n"
    )
    assert actual is not None and len(actual) == 3, actual
    assert actual[0]["status"] == "row" and actual[0]["key"] == "x86:cmp (r32, r32)", actual
    assert actual[1]["status"] == "no-row", actual  # llvm-mc's own error
    assert actual[2]["status"] == "row" and actual[2]["key"] == "x86:test (r32, r32)", actual


@requires_fixtures
def test_trailing_blank_lines_keep_their_rows(browser, tmp_path):
    """Trailing blank lines annotate nothing and the marker map keeps
    them: without it the echo count mismatched and no line got a row
    (probe: 'line mapping unverified (echo 3 vs source ...)')."""
    actual = _identify_doc(browser, tmp_path, "\taddq %rax, %rbx\n\taddl %eax, %ecx\n\n\n")
    assert actual is not None and len(actual) == 4, actual
    assert actual[0]["status"] == "row" and actual[0]["key"] == "x86:add (r64, r64)", actual
    assert actual[1]["status"] == "row" and actual[1]["key"] == "x86:add (r32, r32)", actual
    assert actual[2]["status"] == "not-an-instruction" and actual[2]["reason"] == "blank", actual
    assert actual[3]["status"] == "not-an-instruction" and actual[3]["reason"] == "blank", actual


@requires_fixtures
def test_fixup_and_mode_lines_get_no_row(browser, tmp_path):
    """A fixup placeholder and a non-64-bit mode never decide a row."""
    fixup = _identify_doc(
        browser, tmp_path, "shll $symbol, %eax\naddl $symbol, %eax\n.set symbol, 2"
    )
    assert fixup is not None and len(fixup) == 3, fixup
    for got in fixup[:2]:
        assert got["status"] == "no-row" and "fixup" in got["reason"], fixup
    mode16 = _identify_doc(browser, tmp_path, ".code16\nmovw %ax, %bx\npushw %ax")
    assert mode16 is not None and len(mode16) == 3, mode16
    for got in mode16[1:]:
        assert got["status"] == "no-row" and "16-bit mode" in got["reason"], mode16


@requires_fixtures
def test_missing_worker_script_falls_back(browser, tmp_path):
    """With the shard present but identity.js missing, runAnnotate must
    fall back to name matching instead of hanging on the worker."""
    site = tmp_path / "site"
    _build_site(site, IDIR / "wasm")
    (site / "identity.js").unlink()
    port = _free_port()
    with _serve(site, port):
        page = browser.new_page()
        try:
            page.add_init_script("window.__simdrefWasmBase = location.origin + '/wasm-v1/';")
            page.goto(f"http://127.0.0.1:{port}/")
            page.wait_for_function("() => document.body.dataset.phase2 === 'done'", timeout=60_000)
            page.evaluate(
                "() => { document.querySelector('#ann-input').value = 'addq %rax, %rbx'; return runAnnotate(); }"
            )
            page.wait_for_function(
                "() => document.querySelector('#ann-status').textContent.includes('annotated')",
                timeout=30_000,
            )
            status = page.locator("#ann-status").text_content()
            assert "byte identity unavailable" in status, status
            assert "#" in page.locator("#ann-output").text_content()
        finally:
            page.close()


@requires_fixtures
def test_sha256_mismatch_refuses_wasm(browser, tmp_path):
    """A corrupted llvm-mc.wasm fails the sha256 check, the wasm is never
    instantiated, and the tab falls back to name matching."""
    site = tmp_path / "site"
    _build_site(site, IDIR / "wasm-bad")
    port = _free_port()
    with _serve(site, port):
        page = browser.new_page()
        try:
            page.add_init_script("window.__simdrefWasmBase = location.origin + '/wasm-v1/';")
            page.goto(f"http://127.0.0.1:{port}/")
            page.wait_for_function("() => document.body.dataset.phase2 === 'done'", timeout=60_000)
            page.evaluate(
                "() => { document.querySelector('#ann-input').value = 'addq %rax, %rbx'; return runAnnotate(); }"
            )
            page.wait_for_function(
                "() => document.querySelector('#ann-status').textContent.includes('annotated')",
                timeout=60_000,
            )
            status = page.locator("#ann-status").text_content()
            assert "byte identity unavailable" in status, status
            assert "sha256 mismatch" in status, status
            # The fallback matcher still annotated the line.
            assert "#" in page.locator("#ann-output").text_content()
        finally:
            page.close()
