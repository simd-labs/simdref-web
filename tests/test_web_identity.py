"""Byte identity tests for the Annotate tab.

Drives the real site in headless Chromium against a fixture server that
serves the real ``search-index-encodings.json`` shard and the local
llvm-mc / XED wasm builds (nothing is fetched from GitHub). Compared
per line against the expected rows of the reference implementation
(src/simdref/asm_identity.py, schema-14 catalog).

Fixtures (documents, expected rows, the shard gzipped) are committed
under ``tests/fixtures/identity``; ``SIMDREF_WEB_IDENTITY_DIR`` can
point at another directory with the same layout. The llvm-mc / XED wasm
builds come from the visualizer ``wasm-v1`` release, pointed at through
``SIMDREF_WEB_IDENTITY_WASM``; the tests skip when it is unset, so a
local run without the release download stays green. Layout::

    doc-att.s / expected-att.json       AT&T x86 corpus document + rows
    doc-a64.s / expected-a64.json       AArch64 corpus document + rows
    doc-riscv.s / expected-riscv.json   RISC-V corpus document + rows
    search-index-encodings.json.gz      the real export shard, gzipped

The wasm-bad variant (one byte of llvm-mc.wasm flipped) is built in
``tmp_path`` from the release files.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from test_web_e2e import _free_port, _populate_site, _serve  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "identity"
IDIR = Path(os.environ.get("SIMDREF_WEB_IDENTITY_DIR", FIXTURE_DIR))
WASM_DIR = os.environ.get("SIMDREF_WEB_IDENTITY_WASM")

requires_fixtures = pytest.mark.skipif(
    WASM_DIR is None,
    reason="SIMDREF_WEB_IDENTITY_WASM unset (no wasm-v1 release download)",
)

WASM_FILES = ("llvm-mc.js", "llvm-mc.wasm", "xedform.cjs", "xedform.wasm")


def _copy_shard(out: Path) -> None:
    shard = IDIR / "search-index-encodings.json"
    if shard.exists():
        shutil.copy(shard, out / "search-index-encodings.json")
    else:
        with gzip.open(IDIR / "search-index-encodings.json.gz", "rb") as f:
            (out / "search-index-encodings.json").write_bytes(f.read())


def _build_site(out: Path, wasm_source: Path | str | None = None) -> None:
    _populate_site(out)
    shutil.copy(REPO_ROOT / "web" / "identity.js", out / "identity.js")
    _copy_shard(out)
    wasm_dir = out / "wasm-v1"
    wasm_dir.mkdir()
    source = Path(wasm_source) if wasm_source is not None else Path(WASM_DIR)
    for name in WASM_FILES:
        shutil.copy(source / name, wasm_dir / name)


def _bad_wasm(tmp_path: Path) -> Path:
    """Copy the release wasm dir and flip one byte of llvm-mc.wasm."""
    bad = tmp_path / "wasm-bad"
    shutil.copytree(WASM_DIR, bad)
    wasm = bad / "llvm-mc.wasm"
    data = bytearray(wasm.read_bytes())
    data[-1] ^= 0xFF
    wasm.write_bytes(data)
    return bad


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
    _build_site(site)
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
    _build_site(site)
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
    _build_site(site)
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
    _build_site(site)
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
def test_mode_in_inactive_if_body_gets_no_row(browser, tmp_path):
    """The .code64 sits in a skipped .if 0 body, so the movw assembles
    in 16-bit mode (Sol's blocker P2 verbatim, asm_identity commit
    c1c4c9b: the mode rides the llvm-mc output stream)."""
    actual = _identify_doc(browser, tmp_path, ".code16\n.if 0\n.code64\n.endif\nmovw %ax, %bx")
    assert actual is not None and len(actual) == 5, actual
    assert actual[4]["status"] == "no-row" and "16-bit mode" in actual[4]["reason"], actual


@requires_fixtures
def test_mode_in_macro_body_gets_no_row(browser, tmp_path):
    """The .code64 is macro body text only; the movw runs in 16-bit mode."""
    actual = _identify_doc(browser, tmp_path, ".code16\n.macro up\n.code64\n.endm\nmovw %ax, %bx")
    assert actual is not None and len(actual) == 5, actual
    assert actual[4]["status"] == "no-row" and "16-bit mode" in actual[4]["reason"], actual


@requires_fixtures
def test_mode_in_comment_gets_no_row(browser, tmp_path):
    """The .code64 is block-comment text; the movw runs in 16-bit mode."""
    actual = _identify_doc(browser, tmp_path, ".code16\n/*\n.code64\n*/\nmovw %ax, %bx")
    assert actual is not None and len(actual) == 5, actual
    assert actual[4]["status"] == "no-row" and "16-bit mode" in actual[4]["reason"], actual


@requires_fixtures
def test_mode_after_semicolon_statement_gets_no_row(browser, tmp_path):
    """The "; .code16" statement executes after the nop: the nop keeps its
    row (64-bit mode) and the movw runs in 16-bit mode."""
    actual = _identify_doc(browser, tmp_path, "nop; .code16\nmovw %ax, %bx")
    assert actual is not None and len(actual) == 2, actual
    assert actual[0]["status"] == "row", actual
    assert actual[1]["status"] == "no-row" and "16-bit mode" in actual[1]["reason"], actual


@requires_fixtures
def test_mode_in_inactive_else_branch_gets_no_row(browser, tmp_path):
    """The .code64 sits in the skipped .else branch; the movl runs in
    32-bit mode (llvm-mc MOV32rr)."""
    actual = _identify_doc(
        browser, tmp_path, ".code16\n.if 1\n.code32\n.else\n.code64\n.endif\nmovl %eax, %ebx"
    )
    assert actual is not None and len(actual) == 7, actual
    assert actual[6]["status"] == "no-row" and "32-bit mode" in actual[6]["reason"], actual


@requires_fixtures
def test_missing_worker_script_falls_back(browser, tmp_path):
    """With the shard present but identity.js missing, runAnnotate must
    fall back to name matching instead of hanging on the worker."""
    site = tmp_path / "site"
    _build_site(site)
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
    _build_site(site, _bad_wasm(tmp_path))
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


@requires_fixtures
def test_form_feed_keeps_the_line_map(browser, tmp_path):
    """Sol CHECK2-integration probe, recast on the entries the committed
    site-data fixture carries (ADDPS/VADDPS): with a form feed in the
    document the page must split lines by the worker's rule, so the
    second and third lines keep their own rows and the last line never
    picks the shifted vaddps row."""
    site = tmp_path / "site"
    _build_site(site)
    port = _free_port()
    with _serve(site, port):
        page = browser.new_page()
        try:
            page.add_init_script("window.__simdrefWasmBase = location.origin + '/wasm-v1/';")
            page.goto(f"http://127.0.0.1:{port}/")
            page.wait_for_function("() => document.body.dataset.phase2 === 'done'", timeout=60_000)
            keys = page.evaluate(
                """async () => {
                    const keys = [];
                    const original = formatAnnotation;
                    formatAnnotation = function (e, m, o) { keys.push(e.key); return original(e, m, o); };
                    try {
                        document.querySelector('#ann-input').value = 'addps %xmm0, %xmm1\\n\\x0cvaddps %ymm0, %ymm1, %ymm2\\naddps %xmm4, %xmm5\\n';
                        document.querySelector('#ann-isa').value = 'x86';
                        await runAnnotate();
                        return keys;
                    } finally { formatAnnotation = original; }
                }"""
            )
        finally:
            page.close()
    assert keys == [
        "x86:addps (xmm, xmm)",
        "x86:vaddps (ymm, ymm, ymm)",
        "x86:addps (xmm, xmm)",
    ], keys


@requires_fixtures
def test_print_pollution_keeps_16bit_mode_no_row(browser, tmp_path):
    """Sol's .print defect (the Python reference fix, same mechanism):
    .print text on stdout must never flip the mode. Here .code16 set
    16-bit mode and '.print ".code64"' only looks like a mode flag;
    LLVM encodes movw as MOV16rr (89 c3), so it gets no row, never
    x86:mov (r32, r32)."""
    document = ".code16\n" + "nop\n" * 1500 + '.print ""\n.print ".code64"\nmovw %ax, %bx'
    actual = _identify_doc(browser, tmp_path, document)
    assert actual is not None and len(actual) == 1504, actual
    assert actual[0]["status"] == "not-an-instruction", actual[:3]
    assert actual[1]["status"] == "no-row" and "16-bit mode" in actual[1]["reason"], actual[1]
    assert actual[-1]["status"] == "no-row" and "16-bit mode" in actual[-1]["reason"], actual[-1]


@requires_fixtures
def test_print_pollution_keeps_64bit_row(browser, tmp_path):
    """The counterpart: in 64-bit mode '.print ".code16"' must not
    decline a following 64-bit instruction."""
    actual = _identify_doc(browser, tmp_path, '.print ".code16"\nmovl %eax, %ebx')
    assert actual is not None and len(actual) == 2, actual
    assert actual[0]["status"] == "not-an-instruction", actual
    assert actual[1]["status"] == "row" and actual[1]["key"] == "x86:mov (r32, r32)", actual


@requires_fixtures
def test_worker_death_before_ready_settles(browser, tmp_path):
    """Sol CHECK2-init-death probe, verbatim worker body: a worker that
    closes before posting ready must not hang Annotate. The deadline
    from request start expires, the worker is terminated, and the old
    name matcher answers."""
    site = tmp_path / "site"
    _build_site(site)
    port = _free_port()
    with _serve(site, port):
        context = browser.new_context()
        page = context.new_page()
        try:
            page.add_init_script("window.__simdrefWasmBase = location.origin + '/wasm-v1/';")
            page.route(
                "**/identity.js",
                lambda route: route.fulfill(
                    status=200,
                    content_type="text/javascript",
                    body="self.onmessage=()=>self.close();",
                ),
            )
            page.goto(f"http://127.0.0.1:{port}/")
            page.wait_for_function("() => document.body.dataset.phase2 === 'done'", timeout=60_000)
            page.evaluate(
                "() => { document.querySelector('#ann-input').value = 'addq %rax, %rbx';"
                " document.querySelector('#ann-isa').value = 'x86';"
                " window.__settled = false;"
                " window.__run = runAnnotate().then(() => window.__settled = true); }"
            )
            page.wait_for_function("() => window.__settled === true", timeout=90_000)
            status = page.locator("#ann-status").text_content()
            assert "byte identity unavailable" in status, status
            assert "#" in page.locator("#ann-output").text_content()
        finally:
            page.close()
            context.close()
