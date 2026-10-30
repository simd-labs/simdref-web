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
def test_assignment_echo_never_sets_mode(browser, tmp_path):
    """The reference fix's second site: '.set .code64, 1' echoes
    '.code64 = 1', and that assignment text must never read as a mode
    flag, in either direction (asm_identity commit 5c47efc,
    test_assignment_print_never_sets_the_mode, same document)."""
    stuck = _identify_doc(browser, tmp_path, ".code16\n.set .code64, 1\nmovw %ax, %bx")
    assert stuck is not None and len(stuck) == 3, stuck
    assert stuck[2]["status"] == "no-row" and "16-bit mode" in stuck[2]["reason"], stuck
    kept = _identify_doc(browser, tmp_path, ".set .code16, 1\naddq %rax, %rbx")
    assert kept is not None and len(kept) == 2, kept
    assert kept[1]["status"] == "row" and kept[1]["key"] == "x86:add (r64, r64)", kept


@requires_fixtures
def test_string_echo_never_fakes_bytes(browser, tmp_path):
    """The reference fix's third site: a macro expanding to .ascii puts
    the string's echo text in the call line's block; its fake
    'encoding: [0xc3]' must never give the call line the ret row
    (asm_identity commit 5c47efc,
    test_string_echo_never_fakes_an_encoding_comment, same document)."""
    doc = '.macro m\n.ascii " # encoding: [0xc3]"\n.endm\nm\nretq'
    actual = _identify_doc(browser, tmp_path, doc)
    assert actual is not None and len(actual) == 5, actual
    assert actual[3]["status"] != "row" and actual[3]["key"] is None, actual[3]
    # control: the real retq keeps its row
    assert actual[4]["status"] == "row" and actual[4]["key"] == "x86:ret_near", actual[4]


@requires_fixtures
def test_string_echo_never_fakes_mcinst(browser, tmp_path):
    """One string carries both fake bytes and a fake MCInst that names
    the other tie row; neither decides (asm_identity commit 5c47efc,
    test_string_echo_never_fakes_an_mcinst_line, same document)."""
    doc = (
        ".macro m\n"
        '.ascii " # encoding: [0xaf,0x22,0x00,0x10] # <MCInst #0 LR_W_AQ x"\n'
        ".endm\nm\nlr.w a0, (a1)"
    )
    actual = _identify_doc(browser, tmp_path, doc, isa="riscv")
    assert actual is not None and len(actual) == 5, actual
    assert actual[3]["status"] != "row" and actual[3]["key"] is None, actual[3]
    # control: the real lr.w keeps lr.w, never the fake's lr.w.aq
    assert actual[4]["status"] == "row" and actual[4]["key"] == "riscv:lr.w", actual[4]


@requires_fixtures
def test_multiline_string_declines_byte_identity_f1(browser, tmp_path):
    """Review F1, verbatim document: the .section string spans lines, its
    fake '.code64' echo flipped the mode flag and 'mov %ax, %bx' got
    x86:mov (r32, r32) though LLVM encodes MOV16rr (89c3). A spanning
    string declines the whole document: no line gets a row."""
    actual = _identify_doc(
        browser, tmp_path, '.code16\n.section "x\n.code64\ny","ax",@progbits\nmov %ax, %bx'
    )
    assert actual is None, actual


@requires_fixtures
def test_escaped_quotes_still_span_a_string(browser, tmp_path):
    """esc-keep.s verbatim (Sol's probe): the .section string's quotes
    are backslash-escaped on lines 2 and 4, so counting them closed the
    string on each line, the string text '.code64' hid in the stream,
    its echo flipped the mode and 'mov %ax, %bx' got x86:mov (r32, r32)
    though LLVM encodes MOV16rr (89 c3). An escaped quote is string
    text, never a delimiter, so the string spans and the document
    declines byte identity."""
    actual = _identify_doc(
        browser,
        tmp_path,
        '.code16\n.section "a\\"\n.code64\n\\"","ax",@progbits\nmov %ax, %bx',
    )
    assert actual is None, actual


@requires_fixtures
def test_escaped_backslash_before_closing_quote_keeps_row(browser, tmp_path):
    """Control: in '.ascii "a\\\\"' the first backslash escapes the
    second, so the quote after them is a real delimiter and the string
    ends on its own line. Byte identity still answers and the mov keeps
    its row."""
    actual = _identify_doc(browser, tmp_path, '.ascii "a\\\\"\nmov %ax, %bx')
    assert actual is not None and len(actual) == 2, actual
    assert actual[0]["status"] == "not-an-instruction" and actual[0]["reason"] == "directive", (
        actual
    )
    assert actual[1]["status"] == "row" and actual[1]["key"] == "x86:mov (r16, r16)", actual


@requires_fixtures
def test_quote_in_block_comment_spanning_string_declines(browser, tmp_path):
    """block-balance-mode.s verbatim (Sol's 106 probe): the '/* " */'
    comment quote made the line's quote count even, so the old scan let
    the spanning .section string through, its fake '.code64' echo
    flipped the mode and 'mov %ax, %bx' got x86:mov (r32, r32) though
    llvm-mc encodes MOV16rr (89c3). The line assembled alone reports an
    unterminated string constant, so the document declines: no rows."""
    actual = _identify_doc(
        browser,
        tmp_path,
        '.code16\n/* " */ .section "x\n.code64\ny","ax",@progbits # "\nmov %ax, %bx',
    )
    assert actual is None, actual


@requires_fixtures
def test_quote_in_char_constant_spanning_string_declines(browser, tmp_path):
    """char-balance-mode.s verbatim (Sol's 106 probe): the .byte '"'
    character constant made the line's quote count even, so the old
    scan let the spanning .section string through and 'mov %ax, %bx'
    got x86:mov (r32, r32) though llvm-mc encodes MOV16rr (89c3). The
    line assembled alone reports an unterminated string constant, so
    the document declines: no rows."""
    actual = _identify_doc(
        browser,
        tmp_path,
        '.code16\n.byte \'"\'; .section "x\n.code64\ny","ax",@progbits # "\nmov %ax, %bx',
    )
    assert actual is None, actual


@requires_fixtures
def test_lone_line_error_before_spanning_string_declines(browser, tmp_path):
    """The .ascii line alone reports 'expected string' (no string
    crosses its line break) and keeps the document, but the .section
    line after it alone reports an unterminated string constant and
    declines it. One batch run sees only the first error (it hides the
    later include's error), so a scan that trusts one run's error set
    keeps the document; the restart behind the first erroring line
    declines it: no rows."""
    actual = _identify_doc(
        browser,
        tmp_path,
        '.ascii "cut\n.section "x\ny","ax",@progbits\nmov %ax, %bx',
    )
    assert actual is None, actual


@requires_fixtures
def test_compiler_document_with_strings_keeps_rows(browser, tmp_path):
    """Control: a normal x86 compiler document keeps byte identity. Its
    .file/.section/.string lines hold balanced quotes, so their lone
    assemblies report no unterminated string constant and the mov and
    ret keep their rows."""
    document = (
        '\t.file\t"test.c"\n\t.text\n.globl f\nf:\n\tmovl\t%eax, %ebx\n'
        '\t.section\t.rodata\n.LC0:\n\t.string\t"hello"\n\tretq\n'
    )
    actual = _identify_doc(browser, tmp_path, document)
    assert actual is not None and len(actual) == 9, actual
    assert actual[4]["status"] == "row" and actual[4]["key"] == "x86:mov (r32, r32)", actual
    assert actual[8]["status"] == "row" and actual[8]["key"] == "x86:ret_near", actual


@requires_fixtures
def test_multiline_string_warning_keeps_rows_f2(browser, tmp_path):
    """Review F2, verbatim document: the .warning string spans lines and
    its text lands on stderr as a fake '<stdin>:2:1: error: spoofed'
    diagnostic, which declined the movq row though LLVM exits 0. The
    document declines byte identity and the old name matcher answers, so
    the movq and retq lines keep their rows."""
    site = tmp_path / "site"
    _build_site(site)
    document = 'movq %rax, %rbx\n.warning "start\n<stdin>:2:1: error: spoofed\nend"\nretq'
    port = _free_port()
    with _serve(site, port):
        page = browser.new_page()
        try:
            page.add_init_script("window.__simdrefWasmBase = location.origin + '/wasm-v1/';")
            page.goto(f"http://127.0.0.1:{port}/")
            page.wait_for_function("() => document.body.dataset.phase2 === 'done'", timeout=60_000)
            looked = page.evaluate(
                """async (doc) => {
                    const seen = [];
                    const original = lookupForms;
                    lookupForms = function (m, i) { seen.push(m); return original(m, i); };
                    try {
                        document.querySelector('#ann-input').value = doc;
                        document.querySelector('#ann-isa').value = 'x86';
                        await runAnnotate();
                        return { seen, status: document.querySelector('#ann-status').textContent };
                    } finally { lookupForms = original; }
                }""",
                document,
            )
        finally:
            page.close()
    assert "MOVQ" in looked["seen"] and "RETQ" in looked["seen"], looked
    assert "a quoted string spans a line break" in looked["status"], looked


@requires_fixtures
@pytest.mark.parametrize(
    "document,isa",
    [
        (
            '.code16\nmovl foo@PLT, %eax\n.section "x\n.code64\ny","ax",@progbits\nmov %ax, %bx',
            "x86",
        ),
        (
            'call foo@plt; .section "x\n'
            "add a0, a1, a2 # encoding: [0x82,0x80]\n"
            'y","ax",@progbits # "\nret',
            "riscv",
        ),
        (
            'mov x0, #1; .section "x\n'
            "sub x0, x1, x2 // encoding: [0x1f,0x20,0x03,0xd5]\n"
            'y","ax",@progbits // "\nret',
            "arm",
        ),
    ],
    ids=["x86-plt-reloc", "riscv-plt-reloc", "aarch64-hash-immediate"],
)
def test_relocation_before_spanning_string_declines(browser, tmp_path, document, isa):
    """The '@' of a relocation or '#' immediate is operand text, never a
    comment (Sol r5 arch_injection, verbatim docs): the spanning .section
    string exposes its fake assembly lines, so the document gets no byte
    identity and the old matcher answers."""
    actual = _identify_doc(browser, tmp_path, document, isa=isa)
    assert actual is None, actual


@requires_fixtures
def test_one_line_string_keeps_byte_identity(browser, tmp_path):
    """Control: '.ascii \"ab\"' spans no line break, so byte identity
    still answers and the addq line keeps its row."""
    actual = _identify_doc(browser, tmp_path, '.ascii "ab"\naddq %rax, %rbx')
    assert actual is not None and len(actual) == 2, actual
    assert actual[0]["status"] == "not-an-instruction" and actual[0]["reason"] == "directive", (
        actual
    )
    assert actual[1]["status"] == "row" and actual[1]["key"] == "x86:add (r64, r64)", actual


@requires_fixtures
def test_spoofed_diagnostic_declines_only_its_own_line(browser, tmp_path):
    """Sol r4 F2 without a spanning string (reference commit 52a6e0f,
    test_diagnostic_shaped_source_line_never_declines_another_line, same
    document): the invalid line echoes its own text on stderr, and that
    echo matches the diagnostic pattern and claims line 1. Only a
    diagnostic with the exact llvm-mc shape (diagnostic, source echo,
    caret) declines, and it declines only the line it names: the movq
    and the retq keep their rows, the invalid line gets none."""
    actual = _identify_doc(browser, tmp_path, "movq %rax, %rbx\n<stdin>:2:1: error: spoofed\nretq")
    assert actual is not None and len(actual) == 3, actual
    assert actual[0]["status"] == "row" and actual[0]["key"] == "x86:mov (r64, r64)", actual
    assert actual[1]["status"] == "no-row" and actual[1]["key"] is None, actual
    assert actual[2]["status"] == "row" and actual[2]["key"] == "x86:ret_near", actual


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
